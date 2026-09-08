"""唯一分钟状态推进核心（BE-13 第二批 · 评审问题 6/7）。

`advance_one_minute` 是全系统唯一的「每分钟确定性状态推进」：

- 候选方案预测：`engine.simulate_dispatch_candidate` 在状态副本（深拷贝）上循环调用，
  直到控制、超时或资源耗尽；
- 正式任务执行：`engine.simulate_monitor` 在任务真实状态上循环调用，界面 5 分钟刷新
  即连续推进 N×1 分钟后汇总，不再存在另一套「5 分钟算法」。

增长、飞行、处置、SOC、补给、换电、排队和库存全部使用同一套规则；预测不得修改
正式状态（调用方负责深拷贝）。每分钟固定顺序：

1. 推进各机当前相位（飞行/作业/返航/补给/换电/充电/悬停）；
2. 满足到场条件的无人机进入作业；
3. 按每架无人机自己的模块扣减药剂（W20 计升、C6 计千克，κ 按「本机模块×火型」查表）；
4. 累计本分钟有效处置量；
5. 更新 SOC；
6. 判定返航、补给、换电与接替（服务计时并行、随机队记录跨轮持久）；
7. 扣减/更新库存（基地补水、C6 换模块、就地取水、备用电池）；
8. 火势净更新（比例增长率复利 − 本分钟处置）；
9. 记录本分钟事件、资源变化与状态标志。

相位进度（_phase_elapsed/_phase_minutes/_outbound_minutes）与服务计时器
（_swap_left/_refill_left/_c6_left）都挂在无人机记录上，随机队快照跨轮持久。
"""
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .engine import _agent_kappa, _module_agent, _pick_water_source, v1_config

SERVICE_TIMERS = ("_swap_left", "_refill_left", "_c6_left")


def create_simulation_state(
    fleet: List[Dict[str, Any]],
    inventory: Dict[str, Any],
    plan: Dict[str, Any],
    fire_load_flp: float,
    fire_type: str = "vegetation",
    eta: float = 0.9,
    spray_cap: Optional[float] = None,
) -> Dict[str, Any]:
    """由方案构建仿真状态：初始化执行态相位、计数器与标志。

    fleet/inventory 必须已归一化；调用方保证字典可变（预测侧先深拷贝）。
    """
    selected_ids = set(plan.get("firefighting_uavs") or [u for u in plan.get("selected_uavs", []) if str(u).startswith("E")])
    plan_by_uav = {entry.get("uav_id"): entry for entry in plan.get("battery_plan", [])}
    for drone in fleet:
        uid = drone.get("uav_id")
        status = drone.get("status")
        entry = plan_by_uav.get(uid) or {}
        if uid in selected_ids and status in {"available", "assigned"}:
            outbound = max(0.5, float(entry.get("outbound_minutes", 1.0)))
            drone["status"] = "flying"
            drone["_phase_elapsed"] = 0.0
            drone["_phase_minutes"] = outbound
            drone["_outbound_minutes"] = outbound
        elif status == "flying" and uid not in selected_ids:
            # 重规划换名单后不在新 selected_ids 的在途机视为携带旧任务，召回返航
            outbound = max(0.5, float(entry.get("outbound_minutes", 4.0)))
            drone["status"] = "returning"
            drone["_phase_elapsed"] = 0.0
            drone["_phase_minutes"] = outbound
            drone["_outbound_minutes"] = outbound
        elif status in {"flying", "returning"}:
            # 在途机续接既有进度，禁止归零重飞（旧档缺键按当前状态补默认航程；
            # battery_plan 已随每轮回写 outbound_minutes，正常路径不会再缺）。
            default_outbound = 1.0 if status == "flying" else 4.0
            outbound = max(0.5, float(entry.get("outbound_minutes", default_outbound)))
            drone.setdefault("_outbound_minutes", outbound)
            drone.setdefault("_phase_minutes", outbound)
            drone.setdefault("_phase_elapsed", 0.0)
    config = v1_config()
    charging_cfg = config.get("charging") or {}
    refill_cfg = config.get("refill_minutes") or {}
    return {
        "fleet": fleet,
        "inventory": inventory,
        "fire_load_flp": max(0.0, float(fire_load_flp)),
        "fire_type": fire_type,
        "module": plan.get("material_module", "water_20l"),
        "eta": float(eta),
        "selected_ids": selected_ids,
        "spray_cap": spray_cap,
        "minute": 0,
        "minute_suppression": 0.0,
        "suppression_total": 0.0,
        "consumed": 0.0,
        "consumed_water": 0.0,
        "consumed_co2": 0.0,
        "stalled_agent": False,
        "soc_return_risk": False,
        "battery_starved": False,
        "emergency_units": [],
        "emergency_soc": float(config.get("emergency_soc_percent", 15)),
        "swap_minutes": float(charging_cfg.get("battery_swap_minutes", 5)),
        "module_swap_minutes": float(charging_cfg.get("module_swap_minutes", 5)),
        "base_refill_minutes": float(refill_cfg.get("base", 4)),
        "onsite_refill_minutes": float(refill_cfg.get("onsite", 8)),
    }


def _relaunch(state: Dict[str, Any], drone: Dict[str, Any], uid: str) -> None:
    """补给/换电/充电完成后的重新出动（评审测试5：空载禁止复飞）。"""
    if uid in state["selected_ids"] and float(drone.get("agent_remaining", 0)) > 0:
        outbound = max(0.5, float(drone.get("_outbound_minutes") or 1.0))
        drone["status"] = "flying"
        drone["_phase_elapsed"] = 0.0
        drone["_phase_minutes"] = outbound
        drone["_outbound_minutes"] = outbound
    else:
        drone["status"] = "available"
        if uid in state["selected_ids"] and float(drone.get("agent_remaining", 0)) <= 0:
            state["stalled_agent"] = True


def advance_one_minute(state: Dict[str, Any], plan: Dict[str, Any]) -> Dict[str, Any]:
    """推进 1 分钟：原地修改 state，返回本分钟摘要事件。"""
    fleet = state["fleet"]
    stock = state["inventory"]
    module = state["module"]
    fire_type = state["fire_type"]
    eta = state["eta"]
    minute_suppression = 0.0
    finished_units: List[str] = []
    working_units: List[str] = []
    for drone in fleet:
        uid = drone.get("uav_id", "")
        status = drone.get("status")
        rate = float(drone.get("energy_rate_percent_per_hour", 180))
        if status == "flying":
            drain = rate / 60
            drone["soc"] = max(0.0, round(drone["soc"] - drain, 2))
            drone["_soc_used"] = float(drone.get("_soc_used", 0.0)) + drain
            drone["_phase_elapsed"] = float(drone.get("_phase_elapsed", 0.0)) + 1
            if drone["_phase_elapsed"] >= float(drone.get("_phase_minutes", 1.0)):
                drone["status"] = "working"
                drone["_phase_elapsed"] = 0.0
                drone["_phase_minutes"] = 5.0
                drone["_sorties"] = int(drone.get("_sorties", 0)) + 1
        elif status == "working":
            spray_cap = state["spray_cap"]
            if spray_cap is not None and state["consumed"] >= spray_cap:
                drone["status"] = "returning"
                continue
            if drone["soc"] < 25:
                state["soc_return_risk"] = True
                drone["status"] = "returning"
                continue
            agent = float(drone.get("agent_remaining", 0))
            if agent <= 0:
                drone["status"] = "returning"
                continue
            # 按各机自身 payload_module 计量（评审问题5）：W20 用升、C6 用千克，
            # κ 按「本机模块 × 火型」查表——水打电气火 κ=0 无效，不得混账。
            dmod = str(drone.get("payload_module") or module)
            dcap, drate = _module_agent(dmod)
            dkappa, _dcompat = _agent_kappa(dmod, fire_type)
            sprayed = min(drate, agent, dcap)
            if spray_cap is not None:
                sprayed = min(sprayed, max(0.0, spray_cap - state["consumed"]))
            drone["agent_remaining"] = round(max(0.0, agent - sprayed), 2)
            state["consumed"] += sprayed
            if dmod == "water_20l":
                state["consumed_water"] += sprayed
            else:
                state["consumed_co2"] += sprayed
            gain = sprayed * dkappa * eta
            state["suppression_total"] += gain
            minute_suppression += gain
            working_units.append(uid)
            drain = rate * 1.05 / 60
            drone["soc"] = max(0.0, round(drone["soc"] - drain, 2))
            drone["_soc_used"] = float(drone.get("_soc_used", 0.0)) + drain
            if drone["agent_remaining"] <= 0 or drone["soc"] < 25:
                drone["status"] = "returning"
                if drone["soc"] < 25:
                    state["soc_return_risk"] = True
        elif status == "returning":
            drain = rate / 60
            drone["soc"] = max(0.0, round(drone["soc"] - drain, 2))
            drone["_soc_used"] = float(drone.get("_soc_used", 0.0)) + drain
            drone["_phase_elapsed"] = float(drone.get("_phase_elapsed", 0.0)) + 1
            if drone["_phase_elapsed"] >= float(drone.get("_phase_minutes", 4.0)):
                drone["_phase_elapsed"] = 0.0
                drone["_phase_minutes"] = 4.0
                drone["status"] = "servicing"
        elif status == "servicing":
            # 补给按各机自身模块计量并分别计时：基地补水/就地取水/C6 换模块/换电；
            # 全部计时器并行递减、随机队记录跨轮持久，全部完成才复飞。
            dmod = str(drone.get("payload_module") or module)
            dcap, _drate = _module_agent(dmod)
            if any(float(drone.get(key, 0) or 0) > 0 for key in SERVICE_TIMERS):
                for key in SERVICE_TIMERS:
                    left = float(drone.get(key, 0) or 0)
                    if left > 0:
                        drone[key] = max(0.0, left - 1)
                if all(float(drone.get(key, 0) or 0) <= 0 for key in SERVICE_TIMERS):
                    for key in SERVICE_TIMERS:
                        drone.pop(key, None)
                    _relaunch(state, drone, uid)
                continue
            can_refill = True
            if float(drone.get("agent_remaining", 0)) < dcap:
                if dmod == "water_20l":
                    if stock.get("water_liters", 0) >= dcap and stock.get("water_modules_w20", 0) >= 1:
                        stock["water_liters"] = round(stock["water_liters"] - dcap, 2)
                        stock["water_modules_w20"] = max(0, stock["water_modules_w20"] - 1)
                        drone["agent_remaining"] = dcap
                        drone["_refill_left"] = state["base_refill_minutes"]
                        drone["_refill_count"] = int(drone.get("_refill_count", 0)) + 1
                    else:
                        # 基地不足 → 就地取水（规则 V1 §5.3）：扣水源容量，装满后归队
                        source = _pick_water_source(stock, dcap)
                        if source is not None:
                            source["capacity_liters"] = round(float(source.get("capacity_liters", 0)) - dcap, 2)
                            drone["agent_remaining"] = dcap
                            drone["_refill_left"] = state["onsite_refill_minutes"]
                            drone["_refill_count"] = int(drone.get("_refill_count", 0)) + 1
                        else:
                            can_refill = False
                else:
                    if stock.get("co2_modules_c6", 0) >= 1:
                        stock["co2_modules_c6"] = max(0, stock["co2_modules_c6"] - 1)
                        drone["agent_remaining"] = dcap
                        drone["_c6_left"] = state["module_swap_minutes"]
                        drone["_refill_count"] = int(drone.get("_refill_count", 0)) + 1
                    else:
                        can_refill = False
                if not can_refill:
                    # 空载禁止复飞（评审测试5）：无药剂可补只能待命/充电等补给。
                    state["stalled_agent"] = True
                    drone["status"] = "charging" if drone["soc"] < 100.0 else "available"
                    continue
            # 电池周转（规则 V1 §7）：优先换电（→95%），无备用电池才慢速充电；
            # 与药剂补给计时并行（串行曾白等 5 分钟）。
            if drone["soc"] < 95.0 and stock.get("battery_packs", 0) >= 1:
                stock["battery_packs"] = max(0.0, round(stock["battery_packs"] - 1, 2))
                drone["soc"] = 95.0
                drone["_swap_left"] = state["swap_minutes"]
                drone["_swap_count"] = int(drone.get("_swap_count", 0)) + 1
            elif drone["soc"] < 100.0:
                if stock.get("battery_packs", 0) < 1:
                    state["battery_starved"] = True
                drone["status"] = "charging"
            if any(float(drone.get(key, 0) or 0) > 0 for key in SERVICE_TIMERS):
                continue
            if drone["status"] == "servicing":
                _relaunch(state, drone, uid)
        elif status == "charging":
            drone["soc"] = round(min(100.0, drone["soc"] + 100.0 / 60), 2)
            if drone["soc"] >= 100.0:
                _relaunch(state, drone, uid)
        else:
            # R/S 及待命无人机按悬停耗电缓慢下降；低于 45% 自动回充保持可出动。
            drain = rate * 0.75 / 60
            drone["soc"] = max(0.0, round(drone["soc"] - drain, 2))
            drone["_soc_used"] = float(drone.get("_soc_used", 0.0)) + drain
            if drone["soc"] < 45.0:
                drone["status"] = "charging"
        if 0.0 < drone.get("soc", 0) < state["emergency_soc"] and uid not in state["emergency_units"]:
            state["emergency_units"].append(uid)
        drone["battery"] = drone["soc"]
        drone["payload"] = drone["agent_remaining"]
        drone["last_updated"] = datetime.now().isoformat(timespec="seconds")
    state["minute"] += 1
    state["minute_suppression"] = minute_suppression
    # 火势净更新：比例增长率按分钟复利（分母是方案基线 → rate 为常数，余烬不复燃）
    state["fire_load_flp"] = max(0.0, state["fire_load_flp"] * (1.0 + float(plan.get("growth_rate_per_hour") or 0.0) / 60.0) - minute_suppression)
    return {
        "minute": state["minute"],
        "minute_suppression": round(minute_suppression, 4),
        "fire_load_flp": round(state["fire_load_flp"], 4),
        "working_units": working_units,
        "finished_units": finished_units,
        "consumed_water": round(state["consumed_water"], 2),
        "consumed_co2": round(state["consumed_co2"], 2),
    }


def fleet_all_idle(state: Dict[str, Any]) -> bool:
    """全员脱离执行链（无飞行/作业/返航/服务/充电，且无计时器在跑）→ 预测可提前终止。"""
    for drone in state["fleet"]:
        if drone.get("status") in {"flying", "working", "returning", "servicing", "charging"}:
            return False
        if any(float(drone.get(key, 0) or 0) > 0 for key in SERVICE_TIMERS):
            return False
    return True
