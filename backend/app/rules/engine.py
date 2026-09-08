"""确定性规则引擎（AG-4）：全部安全关键数值的唯一来源。

本模块由 tools/core.py 与 pipeline.py 原样迁入（冻结公式，禁止修改数值逻辑）：
FLP 网格（B_i = 10×I×K_fuel×K_wind×K_slope）、J 评分权重、κ 药剂表、风档/坡度系数、
SOC 阈值（25 返航 / 35 接新 / 15 应急）、离散仿真（simulate_dispatch_candidate /
simulate_monitor）、V1 调度（deterministic_v1_dispatch）、取水六条件、场景加载。
"""
import json
import math
import itertools
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..domain.schemas import InventorySnapshot, UAVRecord

# 项目根（与迁出前 tools/core.py、pipeline.py 的 ROOT 指向一致）
ROOT = Path(__file__).resolve().parents[3]

# 紫霞湖水库（OSM 实测）：演训模拟场景的机群基地锚点（FE-18）
ZIXIAHU_BASE_GPS = (32.062229, 118.839016)


def read_json(path: str) -> Any:
    with (ROOT / path).open(encoding="utf-8") as file:
        return json.load(file)


@lru_cache(maxsize=1)
def v1_config() -> Dict[str, Any]:
    try:
        return read_json("configs/simulation.json").get("v1", {})
    except (OSError, json.JSONDecodeError):
        return {}


def calculate_distance(origin: Dict[str, float], target: Dict[str, float], speed_mps: float = 10, **_: Any) -> Dict[str, float]:
    positive(speed_mps, "speed_mps")
    distance = math.hypot(target["x"] - origin["x"], target["y"] - origin["y"])
    return {"distance_m": round(distance, 2), "estimated_minutes": round(distance / speed_mps / 60, 2)}


def positive(value: float, name: str) -> float:
    if value < 0:
        raise ToolError("invalid_input", name + " 不能为负数")
    return value


def resolve_wind_band(wind_speed: float = 0, **_: Any) -> Dict[str, Any]:
    ws = positive(wind_speed, "wind_speed")
    bands = v1_config().get("wind_bands") or [{"max_mps": 4.0, "k_wind": 1.0, "label": "0–4 m/s"}, {"max_mps": 6.0, "k_wind": 1.2, "label": "4–6 m/s"}, {"max_mps": 8.0, "k_wind": 1.5, "label": "6–8 m/s"}]
    for band in bands:
        if ws < band["max_mps"]:
            return {"band": bands.index(band), "label": band["label"], "k_wind": band["k_wind"], "wind_speed": ws}
    return {"band": len(bands), "label": ">8 m/s", "k_wind": v1_config().get("k_wind_over", 1.5), "wind_speed": ws}


def resolve_slope_factor(slope_deg: float = 0, **_: Any) -> Dict[str, Any]:
    value = positive(slope_deg, "slope_deg")
    bands = v1_config().get("slope_bands") or [{"max_deg": 15.0, "k_slope": 1.0}, {"max_deg": 30.0, "k_slope": 1.15}, {"max_deg": 90.0, "k_slope": 1.3}]
    for band in bands:
        if value < band["max_deg"]:
            return {"k_slope": band["k_slope"], "slope_deg": value}
    return {"k_slope": bands[-1]["k_slope"], "slope_deg": value}


def calculate_flp_load(cells: list = None, intensity: float = 1, fuel_factor: float = 1.0, wind_factor: float = 1.0, slope_factor: float = 1.0, **_: Any) -> Dict[str, Any]:
    # cells 兼容 k_fuel/k_wind/k_slope（build_fire_grid 记法）与 fuel_factor/wind_factor/slope_factor 两种键名，
    # 冻结公式 B_i = 10 × I × K_fuel × K_wind × K_slope 的每个因子都必须生效。
    if cells is None: cells = [{"intensity": intensity, "fuel_factor": fuel_factor, "wind_factor": wind_factor, "slope_factor": slope_factor}]
    loads = [
        10 * c.get("intensity", 1)
        * c.get("fuel_factor", c.get("k_fuel", 1))
        * c.get("wind_factor", c.get("k_wind", 1))
        * c.get("slope_factor", c.get("k_slope", 1))
        for c in cells
    ]
    return {"fire_load_flp": round(sum(loads), 4), "cell_loads_flp": [round(x, 4) for x in loads], "cell_count": len(loads)}


def select_water_source(sources: list = None, distance_m: float = 0, cycle_minutes: float = 0, base_fill_minutes: float = 4, soc_after_cycle: float = 100, route_safe: bool = True, **_: Any) -> Dict[str, Any]:
    candidates = []
    for source in sources or []:
        safe = source.get("safe_access", source.get("safe", False))
        capacity = source.get("capacity_remaining", source.get("capacity_liters", 0))
        saving = base_fill_minutes - (source.get("fill_minutes", 8) + cycle_minutes)
        if source.get("available", False) and safe and capacity >= 20 and route_safe and soc_after_cycle >= 25 and saving >= 5:
            candidates.append((source.get("distance_m", 0), source))
    selected = min(candidates, key=lambda x: x[0])[1] if candidates else None
    return {"selected": bool(selected), "source": selected, "reason": "满足安全、容量、SOC及至少节省5分钟" if selected else "无合格就地水源，改用基地补给"}


def swap_battery(**_: Any) -> Dict[str, Any]:
    config = v1_config().get("charging") or {}
    return {"minutes": float(config.get("battery_swap_minutes", 5)), "soc_after": float(config.get("battery_swap_soc", 95)), "requires_battery_pack": True, "note": "同型号电池换电，库存-1，旧包进入 charging"}


def build_fire_grid(fire_area_m2: float, wind_speed: float = 0, slope_deg: float = 0, fuel_type: str = "general_forest", intensity: float = 2, **_: Any) -> Dict[str, Any]:
    """按 100 m² 网格折算火情负荷 B_total = Σ 10×I×K_fuel×K_wind×K_slope。"""
    positive(fire_area_m2, "fire_area_m2")
    config = v1_config()
    cell_area = float(config.get("grid_cell_m2", 100))
    cell_count = max(1, math.ceil(fire_area_m2 / cell_area))
    band = resolve_wind_band(wind_speed)
    slope = resolve_slope_factor(slope_deg)
    fuel_factors = config.get("fuel_factors") or {"sparse_grass": 0.8, "general_forest": 1.0, "dense_fuel": 1.3}
    k_fuel = float(fuel_factors.get(fuel_type, 1.0))
    cells = [{"cell_id": index, "intensity": intensity, "k_fuel": k_fuel, "k_wind": band["k_wind"], "k_slope": slope["k_slope"]} for index in range(cell_count)]
    loads = calculate_flp_load(cells)["cell_loads_flp"]
    return {
        "cell_area_m2": cell_area, "cell_count": cell_count, "cells": cells,
        "cell_loads_flp": loads, "fire_load_flp": round(sum(loads), 2),
        "intensity": intensity, "k_fuel": k_fuel, "k_wind": band["k_wind"], "k_slope": slope["k_slope"],
        "wind_band": band, "fuel_type": fuel_type,
    }


def simulate_dispatch_candidate(selected: List[Dict[str, Any]] = None, fire_load_flp: float = 0, growth_flp_per_hour: float = 0, module: str = "water_20l", fire_type: str = "vegetation", origin: Dict[str, float] = None, inventory: Dict[str, Any] = None, wind_speed: float = 0, round_minutes: float = 5, max_rounds: int = 24, growth_rate_per_hour: Optional[float] = None, **_: Any) -> Dict[str, Any]:
    """候选组合预测（BE-13 第二批 · 评审问题6）：与正式执行共用 advance_one_minute
    分钟推进核心，在状态副本上推进至控制/超时/资源耗尽——不再存在独立的轮制仿真。

    round_minutes/max_rounds 为兼容参数：预测时间上限 = max_rounds × round_minutes 分钟。
    返回控制时间、剩余 FLP、物资与换电消耗，供多目标评分 J 使用。预测不改正式状态。
    """
    import copy as _copy
    from .simulation import advance_one_minute, create_simulation_state, fleet_all_idle
    config = v1_config()
    band = resolve_wind_band(wind_speed)
    eta = (config.get("drop_efficiency") or {}).get("clear", 0.9) * (config.get("weather_efficiency") or {}).get(f"band{band['band']}", 1.0)
    kappa, compatible = _agent_kappa(module, fire_type)
    origin = origin or {"x": 0, "y": 0}
    load = max(0.0, float(fire_load_flp))
    rate_per_hour = float(growth_rate_per_hour) if growth_rate_per_hour else (float(growth_flp_per_hour) / max(load, 1e-6) if load else 0.0)
    fleet = []
    battery_plan = []
    for uav in selected or []:
        uid = uav.get("uav_id", "?")
        pos = uav.get("position") or origin
        outbound = math.hypot(pos.get("x", 0) - origin.get("x", 0), pos.get("y", 0) - origin.get("y", 0)) / max(float(uav.get("speed_mps", 8)), 0.1) / 60
        battery_plan.append({"uav_id": uid, "outbound_minutes": max(0.5, round(outbound, 2))})
        drone = _copy.deepcopy(uav)
        drone["status"] = "available"
        for key in ("_phase_elapsed", "_phase_minutes", "_outbound_minutes", "_swap_left", "_refill_left", "_c6_left", "_sorties", "_swap_count", "_refill_count", "_soc_used"):
            drone.pop(key, None)
        fleet.append(drone)
    plan = {
        "material_module": module,
        "firefighting_uavs": [u.get("uav_id", "?") for u in selected or []],
        "battery_plan": battery_plan,
        "growth_rate_per_hour": rate_per_hour,
    }
    state = create_simulation_state(
        fleet=fleet, inventory=_copy.deepcopy(inventory or {}), plan=plan,
        fire_load_flp=load, fire_type=fire_type, eta=eta,
    )
    max_minutes = max(1, int(round(max_rounds * round_minutes)))
    minutes_used = 0
    while state["fire_load_flp"] > 0 and minutes_used < max_minutes:
        advance_one_minute(state, plan)
        minutes_used += 1
        if fleet_all_idle(state):
            break  # 全员脱离执行链（空载停摆/待命）且火未灭：无进展可能
    controlled = state["fire_load_flp"] <= 0
    suppression_total = state["suppression_total"]
    material_used = state["consumed"]
    stalled_reason = None
    if not controlled:
        if state["stalled_agent"]:
            stalled_reason = "agent_insufficient"
        elif state["battery_starved"]:
            stalled_reason = "soc_below_return"
        else:
            stalled_reason = "timeout"
    per_uav = []
    for drone in state["fleet"]:
        sorties = int(drone.get("_sorties", 0))
        soc_used = round(float(drone.get("_soc_used", 0.0)), 2)
        per_uav.append({
            "uav_id": drone.get("uav_id", "?"), "soc": drone.get("soc", 0),
            "sortie_soc_cost": round(soc_used / max(sorties, 1), 2), "soc_used": soc_used,
            "sorties": sorties, "swaps": int(drone.get("_swap_count", 0)), "refills": int(drone.get("_refill_count", 0)),
            "state": drone.get("status", "available"),
        })
    growth_per_minute = rate_per_hour * load / 60.0
    return {
        "controlled": controlled, "control_minutes": round(minutes_used, 1) if controlled else None,
        "minutes_used": minutes_used, "rounds_used": max(1, math.ceil(minutes_used / max(round_minutes, 1e-6))),
        "residual_flp": round(state["fire_load_flp"], 2), "suppression_flp": round(suppression_total, 2),
        "growth_unchecked": bool(not controlled and (suppression_total / max(minutes_used, 1)) <= growth_per_minute),
        "material_used": round(material_used, 2), "module": module, "kappa": kappa, "eta": round(eta, 3),
        "swaps": sum(p["swaps"] for p in per_uav), "refills": sum(p["refills"] for p in per_uav),
        "stalled_reason": stalled_reason, "compatible": compatible,
        "per_uav": per_uav,
    }


def score_candidate_plan(control_minutes: Optional[float], residual_flp: float, fire_load_flp: float, energy_total: float, uav_count: int, material_used: float, changes: int, **_: Any) -> Dict[str, Any]:
    """按 J = 0.40T + 0.30B + 0.15E + 0.10M + 0.05N 归一化评分，J 越小越优。"""
    config = v1_config()
    weights = config.get("scoring_weights") or {"time": 0.4, "residual": 0.3, "energy": 0.15, "material": 0.1, "change": 0.05}
    refs = config.get("scoring_refs") or {"time_ref_minutes": 120, "energy_ref_per_uav": 100, "material_ref_liters": 80, "change_ref_rounds": 4}
    time_norm = min(max((control_minutes or refs["time_ref_minutes"] * 2) / refs["time_ref_minutes"], 0), 1) if control_minutes else 1.0
    residual_norm = min(max(residual_flp / max(fire_load_flp, 1), 0), 1)
    energy_norm = min(max(energy_total / max(uav_count * refs["energy_ref_per_uav"], 1), 0), 1)
    material_norm = min(max(material_used / refs["material_ref_liters"], 0), 1)
    change_norm = min(max(changes / refs["change_ref_rounds"], 0), 1)
    score = weights["time"] * time_norm + weights["residual"] * residual_norm + weights["energy"] * energy_norm + weights["material"] * material_norm + weights["change"] * change_norm
    return {"score": round(score, 4), "lower_is_better": True, "parts": {"time": round(time_norm, 3), "residual": round(residual_norm, 3), "energy": round(energy_norm, 3), "material": round(material_norm, 3), "change": round(change_norm, 3)}}


def _agent_kappa(module: str, fire_type: str = "vegetation") -> Tuple[float, bool]:
    # κ 表只分植被/电气两类；油类、化学品火与电气火同用 CO₂ 兼容行（pipeline 的模块选择同此口径）。
    fire_type = {"oil": "electrical", "chemical": "electrical"}.get(fire_type, fire_type)
    kappa_table = v1_config().get("kappa") or {"vegetation": {"water_20l": 1.0, "co2_6kg": 0.25}, "electrical": {"water_20l": 0.0, "co2_6kg": 1.5}}
    kappa = float((kappa_table.get(fire_type) or {}).get(module, 0.0))
    return kappa, kappa > 0


def normalize(value: float, reference: float) -> float:
    return min(max(value / reference, 0), 1)


def normalize_fleet(records: Any) -> list[dict[str, Any]]:
    """将新契约和旧演示字段统一为领域字段，同时保留旧别名。"""
    normalized = []
    for raw in records or []:
        item = dict(raw)
        subgroup = item.get("subgroup") or item.get("role", "support")
        subgroup = "suppression" if subgroup == "firefighting" else subgroup
        payload_module = item.get("payload_module")
        if not payload_module:
            payload_module = "water_20l" if subgroup == "suppression" else "none"
        unit = item.get("agent_unit") or ("L" if payload_module == "water_20l" else "kg")
        item.update({
            "uav_id": item.get("uav_id") or item.get("id"), "subgroup": subgroup,
            "status": item.get("status") if item.get("status") in {"available", "assigned", "flying", "working", "returning", "servicing", "charging", "fault"} else "available",
            "soc": float(item.get("soc", item.get("battery", 0))), "payload_capacity_kg": float(item.get("payload_capacity_kg", 25 if subgroup == "suppression" else 10)),
            "payload_module": payload_module, "agent_remaining": float(item.get("agent_remaining", item.get("payload", 0))), "agent_unit": unit,
            "speed_mps": float(item.get("speed_mps", 8)), "energy_rate_percent_per_hour": float(item.get("energy_rate_percent_per_hour", 180)),
            "signal": float(item.get("signal", 100)), "health": float(item.get("health", 100)), "assigned_task": item.get("assigned_task"),
        })
        item["id"], item["role"], item["battery"], item["payload"] = item["uav_id"], ("firefighting" if subgroup == "suppression" else subgroup), item["soc"], item["agent_remaining"]
        UAVRecord.model_validate(item)
        normalized.append(item)
    return normalized


def normalize_inventory(raw: Any) -> dict[str, Any]:
    item = dict(raw or {})
    item.setdefault("water_modules_w20", 0)
    item.setdefault("co2_modules_c6", 0)
    item.setdefault("support_boxes_sup10", 0)
    item.setdefault("battery_packs", 0)
    item.setdefault("forward_supply_points", [])
    item.setdefault("water_sources", [])
    InventorySnapshot.model_validate(item)
    return item


def load_demo_state(scene_id: str) -> Dict[str, Any]:
    scene = read_json("data/scene.json")
    if scene["scene_id"] != scene_id:
        raise ValueError(f"未知演示场景: {scene_id}")
    return {"scene": scene, "fleet": normalize_fleet(read_json("data/fleet.json")), "inventory": normalize_inventory(read_json("data/inventory.json")), "config": read_json("configs/simulation.json")}


def assess_fire(state: Dict[str, Any], fire_area: Optional[float] = None, smoke_area: Optional[float] = None, growth_rate: Optional[float] = None) -> Dict[str, Any]:
    config, scene = state["config"], state["scene"]
    fire_area = 1800 if fire_area is None else float(fire_area)
    smoke_area = 4200 if smoke_area is None else float(smoke_area)
    growth_rate = 0.42 if growth_rate is None else float(growth_rate)
    wind_speed = scene["wind_speed"]
    weights = config["weights"]
    risk_score = (
        weights["fire_area"] * normalize(fire_area, config["reference_fire_area_m2"])
        + weights["smoke_area"] * normalize(smoke_area, config["reference_smoke_area_m2"])
        + weights["wind_speed"] * normalize(wind_speed, config["reference_wind_speed_mps"])
        + weights["growth_rate"] * growth_rate
    )
    level = 1 + sum(risk_score >= threshold for threshold in config["level_thresholds"])
    labels = {1: "I 级 · 低风险", 2: "II 级 · 中等火情", 3: "III 级 · 高风险", 4: "IV 级 · 极高风险"}
    slope_deg = float(scene.get("slope_deg", 12))
    fuel_type = scene.get("fuel_type", "general_forest")
    intensity = min(4, max(1, level))
    grid = build_fire_grid(fire_area, wind_speed=wind_speed, slope_deg=slope_deg, fuel_type=fuel_type, intensity=intensity)
    fire_load = float(grid["fire_load_flp"])
    band = grid["wind_band"]
    return {
        "level": level, "label": labels[level], "fire_area_m2": fire_area, "smoke_area_m2": smoke_area,
        "confidence": 0.91, "risk_score": round(risk_score, 3), "growth_rate": growth_rate,
        "spread_direction": scene["wind_direction"], "fire_type": scene.get("fire_type", "vegetation"),
        "fire_load_flp": fire_load, "growth_flp_per_hour": round(fire_load * growth_rate, 2),
        # BE-12：本研判自己的 FLP↔面积比率（FLP 公式含强度/燃料/风/坡系数，比率随场景变化）。
        # monitor 与 replan 的面积折算统一用它，禁止再硬编码 180——否则首轮面积跳变近百倍
        "area_per_flp": round(fire_area / max(fire_load, 1e-6), 4),
        "fire_grid": {key: grid[key] for key in ("cell_area_m2", "cell_count", "intensity", "k_fuel", "k_wind", "k_slope", "fuel_type")},
        "wind_band": band, "slope_deg": slope_deg,
    }


def _evaluate_water_plan(scene: Dict[str, Any], inventory: Dict[str, Any]) -> Dict[str, Any]:
    """就地取水六条件评估（规则 V1 §5.3）：全条件通过才改为就地补给，否则基地补给。

    select_water_source 的判定：available、safe_access、capacity≥20L、路线安全、
    取水循环后 SOC≥25%、比基地补给（4 min）至少节省 5 min。
    """
    source = (scene.get("water_sources") or [{}])[0]
    evaluation = select_water_source(
        sources=[{
            "available": source.get("available", False),
            "safe_access": source.get("safe", source.get("safe_access", False)),
            "capacity_remaining": source.get("capacity_remaining", source.get("capacity_liters", 0)),
            "fill_minutes": 8,
            "distance_m": source.get("distance_m", 0),
        }],
        distance_m=source.get("distance_m", 0),
        cycle_minutes=0,
        base_fill_minutes=4,
        soc_after_cycle=100,
        route_safe=True,
    )
    if evaluation.get("selected") and evaluation.get("source"):
        return {"mode": "onsite", "source_id": source.get("name"), "fill_minutes": 8,
                "distance_m": source.get("distance_m", 0), "reason": "就地水源通过六条件评估且节省≥5分钟"}
    return {"mode": "base", "fill_minutes": 4,
            "reason": "优先基地补给；就地取水评估：" + evaluation.get("reason", "未通过")}


def deterministic_v1_dispatch(state: Dict[str, Any], fire: Dict[str, Any], people_status: str = "unknown", constraints: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """V1 调度：枚举 E 组合 → 硬约束过滤 → 5 分钟离散仿真 → 多目标评分 J → 最优/备选方案。

    R 子群全程保持至少 1 架在线监测，S 子群按有人/无人分支分配任务。
    """
    scene, inventory = state["scene"], state["inventory"]
    people_status = people_status if people_status in {"confirmed", "absent", "unknown"} else "unknown"
    fire_type = str(fire.get("fire_type", scene.get("fire_type", "vegetation"))).lower()
    module = "co2_6kg" if fire_type in {"electrical", "oil", "chemical"} else "water_20l"
    quantity = 6.0 if module == "co2_6kg" else 20.0
    constraints = constraints or {}
    max_drones = int(constraints.get("max_drones", 4)) if constraints.get("max_drones") is not None else 4
    disabled_uavs = {str(uid) for uid in (constraints.get("disabled_uavs") or [])}
    required_module = constraints.get("material_module") or constraints.get("module")
    if required_module in {"water_20l", "co2_6kg"}:
        module = required_module
    if module == "co2_6kg":
        quantity = 6.0
    kappa, _compatible = _agent_kappa(module, fire_type)
    fire_load = max(1.0, float(fire.get("fire_load_flp") or fire["fire_area_m2"] / 180.0))
    # BE-13（评审问题4）：比例增长率是场景/观测层参数（研判 growth_rate），只随「新观测
    # 重规划」更新；方案同时落 growth_baseline_flp（生成时点负荷）。approve 盖章的
    # replan_trigger_baseline_flp 只作重规划触发线，不再参与增长计算——审批/重规划
    # 均不得改变火势自然增长速度。
    growth_rate_per_hour = float(fire.get("growth_rate_per_hour") or fire.get("growth_rate", 0.42))
    growth_flp_per_hour = fire_load * growth_rate_per_hour
    wind_speed = float(fire.get("wind_speed", scene.get("wind_speed", 0)))
    band = resolve_wind_band(wind_speed)
    origin = scene.get("fire_origin", {"x": 0, "y": 0})
    # 规则 V1 §4.2：SOC<35% 不得新接远程任务（new_task_floor_soc_percent）；25% 仅为返航硬约束。
    new_task_floor = float(v1_config().get("new_task_floor_soc_percent", 35))
    # 多用途支援机（multi_role，架构纪要§五扩展）可携带灭火模块参与压制
    def _can_fight(u):
        uid = u.get("uav_id", "")
        return uid.startswith("E") or (uid.startswith("S") and u.get("multi_role"))

    # BE-13（评审问题1）：解除写死的 4 架钳位——出动上限与本任务实际可参战的灭火机数
    # 对齐（E1-E6 + multi_role S3/S4 = 8，S3/S4 计入灭火出动上限，前后端同口径）。
    # 默认仍 4；逐数量枚举 1..上限不变，不默认全员出动。
    capable_count = sum(1 for u in state["fleet"] if u.get("uav_id", "") not in disabled_uavs and _can_fight(u))
    max_drones = max(1, min(max_drones, max(capable_count, 1)))

    # BE-13（评审问题5）：候选载荷兼容改双向——水任务只收 water_20l 机、C6 任务只收
    # co2_6kg 机。此前水任务不验载荷，装 C6 的机也能入选，执行时被按方案统一药剂扣减。
    e_candidates = [u for u in state["fleet"] if u.get("uav_id", "") not in disabled_uavs and _can_fight(u) and u.get("status") in {"available", "assigned"} and u.get("health", 0) >= 60 and u.get("soc", 0) >= new_task_floor and u.get("payload_module") == module]
    recon = [u for u in state["fleet"] if u.get("uav_id", "") not in disabled_uavs and u.get("uav_id", "").startswith("R") and u.get("status") in {"available", "assigned"} and u.get("health", 0) >= 60 and u.get("soc", 0) >= new_task_floor]
    support = [u for u in state["fleet"] if u.get("uav_id", "") not in disabled_uavs and u.get("uav_id", "").startswith("S") and u.get("status") in {"available", "assigned"} and u.get("health", 0) >= 60 and u.get("soc", 0) >= new_task_floor]
    if fire.get("wind_band"):
        band = fire["wind_band"]

    scored = []
    for size in range(1, min(max_drones, len(e_candidates)) + 1):
        for selected in itertools.combinations(e_candidates, size):
            simulation = simulate_dispatch_candidate(
                selected=list(selected), fire_load_flp=fire_load, growth_flp_per_hour=growth_flp_per_hour,
                growth_rate_per_hour=growth_rate_per_hour,
                module=module, fire_type=fire_type, origin=origin, inventory=inventory, wind_speed=wind_speed,
            )
            energy_total = sum(entry.get("soc_used", entry["sortie_soc_cost"] * max(entry["sorties"], 1)) for entry in simulation["per_uav"])
            changes = simulation["swaps"] + simulation["refills"]
            score = score_candidate_plan(
                simulation["control_minutes"], simulation["residual_flp"], fire_load,
                energy_total, len(selected), simulation["material_used"], changes,
            )
            scored.append({"selected": selected, "simulation": simulation, "score": score, "energy_total": energy_total, "changes": changes})

    controlled = [entry for entry in scored if entry["simulation"]["controlled"]]
    # 用户硬时限（规则文档 §8.2）：先剔除超时方案；全部超时时仍选最快方案供参考，但判为不可控并输出时限缺口。
    time_limit = constraints.get("target_minutes")
    if time_limit is not None:
        try:
            time_limit = float(time_limit)
        except (TypeError, ValueError):
            time_limit = None
    time_gap = None
    if time_limit is not None and controlled:
        within = [entry for entry in controlled if entry["simulation"]["control_minutes"] is not None and entry["simulation"]["control_minutes"] <= time_limit]
        if within:
            pool = within
        else:
            pool = controlled
            fastest = min(entry["simulation"]["control_minutes"] for entry in controlled if entry["simulation"]["control_minutes"] is not None)
            time_gap = {"resource": "time_limit", "required": round(time_limit, 1), "available": round(fastest, 1), "gap": round(fastest - time_limit, 1), "resource_gap": True}
    else:
        pool = controlled or scored
    chosen = min(pool, key=lambda entry: (entry["score"]["score"], entry["simulation"]["residual_flp"]), default=None)
    if chosen is None:
        chosen = {"selected": (), "simulation": simulate_dispatch_candidate([], fire_load_flp=fire_load, growth_flp_per_hour=growth_flp_per_hour, growth_rate_per_hour=growth_rate_per_hour, module=module, fire_type=fire_type, origin=origin, inventory=inventory, wind_speed=wind_speed), "score": score_candidate_plan(None, fire_load, fire_load, 0, 0, 0, 0), "energy_total": 0.0, "changes": 0}
    ok, selected, battery_plan, total_flp, gaps, errors = (False, (), [], 0.0, [], [])
    selected = chosen["selected"]
    simulation = chosen["simulation"]
    ok = bool(selected) and simulation["controlled"] and time_gap is None
    battery_plan = [
        {
            "uav_id": entry["uav_id"], "soc_before": next((u.get("soc", 0) for u in selected if u.get("uav_id") == entry["uav_id"]), 0),
            "soc_after_return": entry["soc"], "sortie_soc_cost": entry["sortie_soc_cost"], "sorties": entry["sorties"],
            "swaps": entry["swaps"], "refills": entry["refills"], "reserve_percent": 25,
            "state": entry["state"], "outbound_minutes": round(next((math.hypot((u.get("position") or origin).get("x", 0) - origin.get("x", 0), (u.get("position") or origin).get("y", 0) - origin.get("y", 0)) / max(u.get("speed_mps", 8), 0.1) / 60 for u in selected if u.get("uav_id") == entry["uav_id"]), 0.0), 2),
        }
        for entry in simulation["per_uav"]
    ]
    total_flp = simulation["suppression_flp"]
    material_available = inventory.get("co2_modules_c6", 0) * 6 if module == "co2_6kg" else min(inventory.get("water_liters", 0), inventory.get("water_modules_w20", 0) * 20)
    if not simulation["controlled"]:
        gaps.append({"resource": "effective_flp", "required": round(fire_load, 2), "available": round(total_flp, 2), "gap": round(fire_load - total_flp, 2), "resource_gap": True})
    if material_available < simulation["material_used"]:
        gaps.append({"resource": module, "required": round(simulation["material_used"], 2), "available": round(material_available, 2), "gap": round(simulation["material_used"] - material_available, 2), "resource_gap": True})
    if simulation["stalled_reason"] == "soc_below_return":
        gaps.append({"resource": "battery_packs", "required": "换电后继续", "available": inventory.get("battery_packs", 0), "gap": "备用电池不足", "resource_gap": True})
    if not simulation["compatible"]:
        errors.append(f"药剂模块 {module} 与火情类型 {fire_type} 不兼容")
    selected_ids = [u["uav_id"] for u in selected]
    r_ids = [recon[0]["uav_id"]] if recon else []
    fighting_set = set(selected_ids)
    s_support_pool = [u["uav_id"] for u in support if u["uav_id"] not in fighting_set]
    s_ids = s_support_pool[:1] if s_support_pool else []
    tasks = [{"drone_id": r_ids[0], "task": "持续侦察", "branch": "reconnaissance"}] if r_ids else []
    tasks += [{"drone_id": u, "task": "支援灭火" if u.startswith("S") else "主力灭火", "module": module, "target_flp": round(fire_load / max(len(selected), 1), 2)} for u in selected_ids]
    tasks += [{"drone_id": s_ids[0], "task": "通信广播/疏散引导" if people_status == "confirmed" else ("物流补给" if people_status == "absent" else "复核人员与后备侦察"), "branch": "support"}] if s_ids else []
    alternatives = sorted(
        (
            {
                "selected_uavs": [u["uav_id"] for u in entry["selected"]],
                "feasibility": entry["simulation"]["controlled"],
                "effective_flp": round(entry["simulation"]["suppression_flp"], 2),
                "score": entry["score"]["score"],
                "control_minutes": entry["simulation"]["control_minutes"],
            }
            for entry in scored
            if [u["uav_id"] for u in entry["selected"]] != selected_ids
        ),
        key=lambda item: item["score"],
    )[:8]
    control_value = simulation["control_minutes"] if simulation["controlled"] else None
    window = [round(control_value), round(control_value + 5)] if control_value is not None else None
    # 契约（api-contract §7）：不可控时不得输出时间窗口——时限缺口场景把最快方案窗口只留在缺口信息里。
    if time_gap is not None:
        control_value = None
        window = None
    return {
        "schema_version": "uav-dispatch-v1",
        "fleet_shape": {"reconnaissance": 2, "suppression": 6, "support": 4},
        "firefighting_uavs": selected_ids,
        "can_control": bool(ok),
        "feasibility": ok and bool(r_ids) and bool(s_ids),
        "required_drones": max(1, math.ceil(fire_load / max(quantity * kappa * 0.9, 1))),
        "selected_uavs": r_ids + selected_ids + s_ids,
        "recommended_material": "co2" if module == "co2_6kg" else "water",
        "material_module": module,
        "material_amount": round(simulation["material_used"], 2),
        "fire_load_flp": round(fire_load, 2),
        "growth_rate_per_hour": round(growth_rate_per_hour, 4),
        "growth_baseline_flp": round(fire_load, 2),
        "growth_flp_per_hour": round(growth_flp_per_hour, 2),
        "effective_flp": round(total_flp, 2),
        "resource_gap": ([time_gap] if time_gap else []) + gaps + ([{"resource": "hard_constraint", "gap": ";".join(errors), "resource_gap": True}] if errors else []),
        "battery_plan": battery_plan,
        "people_branch": people_status,
        "fire_grid": fire.get("fire_grid"),
        "wind_band": band,
        "scoring": {"method": "J=0.40T+0.30B+0.15E+0.10M+0.05N", "lower_is_better": True, "chosen": chosen["score"], "simulation": {key: simulation[key] for key in ("controlled", "rounds_used", "stalled_reason", "swaps", "refills")}},
        "water_source_plan": _evaluate_water_plan(scene, inventory),
        "replan_trigger": ["fire_load_increase_over_20_percent", "wind_band_changed", "soc_below_return_threshold", "agent_insufficient", "people_status_changed"],
        "estimated_control_time": {"earliest_minutes": window[0] if window else None, "latest_minutes": window[1] if window else None, "window_minutes": window, "unit": "min", "simulated": simulation["controlled"]},
        "estimated_minutes": window[1] if window else None,
        "alternative_plan": alternatives,
        "tasks": tasks,
        "reason": ("V1 离散仿真可控，按 J 评分选出最优组合" if ok else (f"最快可控方案需 {time_gap['available']} 分钟，超过用户时限 {time_gap['required']} 分钟：输出时限缺口" if time_gap else ("V1 硬约束不足：输出资源缺口，需补给或重规划" if selected_ids else "无可用灭火无人机候选"))),
    }


def _pick_water_source(stock: Dict[str, Any], quantity: float) -> Optional[Dict[str, Any]]:
    """规则 V1 §5.3：从库存水源中挑一处可用且安全、剩余容量足够的水源（就近优先）。"""
    sources = [s for s in (stock.get("water_sources") or [])
               if s.get("available") and s.get("safe", True) and float(s.get("capacity_liters", 0)) >= quantity]
    sources.sort(key=lambda s: float(s.get("distance_m", 1e9)))
    return sources[0] if sources else None


def _module_agent(module: str) -> Tuple[float, float]:
    """按模块读冻结喷洒参数（满载量，每分钟喷量）。W20 计升、C6 计千克，禁止混用。"""
    spray = (v1_config().get("spray") or {}).get(module) or {}
    default_quantity = 20.0 if module == "water_20l" else 6.0
    default_rate = 4.0 if module == "water_20l" else 1.5
    return float(spray.get("quantity", default_quantity)), float(spray.get("rate_per_minute", default_rate))


def simulate_monitor(
    analysis: Dict[str, Any],
    elapsed_minutes: float,
    extinguishing_liters: float,
    fleet_snapshot: Optional[list] = None,
    inventory: Optional[Dict[str, Any]] = None,
    image_name: Optional[str] = None,
) -> Dict[str, Any]:
    """闭环监测：按 1 分钟内部步长推进 elapsed_minutes 分钟。

    BE-13 第二批（评审问题6）：分钟推进全部委托统一核心 simulation.advance_one_minute，
    与候选预测（simulate_dispatch_candidate）共用同一套增长/飞行/处置/SOC/补给/库存
    规则；本函数只负责入口归一化与轮次报告汇总。
    """
    from .simulation import advance_one_minute, create_simulation_state
    fire = analysis["fire_assessment"]
    environment = analysis["environment"]
    fleet = normalize_fleet(fleet_snapshot if fleet_snapshot is not None else analysis.get("fleet", []))
    stock = normalize_inventory(inventory if inventory is not None else analysis.get("inventory", {}))
    dispatch = analysis.get("dispatch_plan", {})
    total_minutes = max(1, int(round(float(elapsed_minutes))))
    module = dispatch.get("material_module", "water_20l")
    fire_type = str(fire.get("fire_type", "vegetation")).lower()
    band = resolve_wind_band(environment.get("wind_speed", 0))
    # BE-13：η 统一读冻结配置（drop_efficiency.clear × weather_efficiency.bandN），与
    # 候选预测同口径（旧 monitor 的硬编码数值恰与配置相等，行为不变）。
    eta = (v1_config().get("drop_efficiency") or {}).get("clear", 0.9) * (v1_config().get("weather_efficiency") or {}).get(f"band{band['band']}", 1.0)
    load_before = float(dispatch.get("fire_load_flp", max(1.0, fire.get("fire_area_m2", 1800) / 180.0)))
    # BE-13（评审问题4）：增长参数与审批触发基线彻底分离。growth_rate_per_hour 是
    # 场景/观测层的比例增长率，只随「新观测重规划」更新（replan 携带、approve 不碰）；
    # approve 盖章的 replan_trigger_baseline_flp 只做重规划触发线（趋势闸门/失控安全网）。
    # 旧档回退链：显式比率 → growth_flp_per_hour/growth_baseline_flp → 研判 growth_rate。
    growth_rate_per_hour = float(
        dispatch.get("growth_rate_per_hour")
        or (float(dispatch.get("growth_flp_per_hour") or 0) / max(float(dispatch.get("growth_baseline_flp") or dispatch.get("base_fire_load_flp") or load_before), 1e-6))
        or float(fire.get("growth_rate", 0.42))
    )
    growth_flp_per_hour = round(growth_rate_per_hour * load_before, 2)
    # 多用途支援机（multi_role）参战时计入可用灭火机数（架构纪要§五扩展）
    available_drones = sum(1 for drone in fleet if (drone.get("subgroup") == "suppression" or drone.get("multi_role")) and drone.get("soc", 0) >= 25 and drone.get("health", 0) >= 60)

    # 统一分钟核心：相位初始化（含跨轮续接/召回）、状态机、库存、计时全部在核心内完成
    core_plan = {**dispatch, "growth_rate_per_hour": growth_rate_per_hour}
    state = create_simulation_state(
        fleet=fleet,
        inventory=stock,
        plan=core_plan,
        fire_load_flp=load_before,
        fire_type=fire_type,
        eta=eta,
        spray_cap=float(extinguishing_liters) if extinguishing_liters else None,
    )
    for _ in range(total_minutes):
        advance_one_minute(state, core_plan)

    fire_load = state["fire_load_flp"]
    stalled_agent = state["stalled_agent"]
    soc_return_risk = state["soc_return_risk"]
    suppression_total = state["suppression_total"]
    consumed_water = state["consumed_water"]
    consumed_co2 = state["consumed_co2"]
    selected_ids = state["selected_ids"]
    emergency_units = state["emergency_units"]

    # 补给时已经按整模块扣减库存；在途喷洒只扣减无人机载荷，避免重复扣减。
    stock["last_updated"] = datetime.now().isoformat(timespec="seconds")

    # 面积折算（BE-12）：用研判时的真实比率（area_per_flp，随场景 FLP 系数变化），
    # 旧数据缺字段回退 180。硬编码 180 曾让首轮面积从 2400m² 跳到 20 万 m²（近百倍）。
    area_ratio = float(fire.get("area_per_flp") or 180.0)
    next_area = round(fire_load * area_ratio)
    previous_area = round(load_before * area_ratio)
    ratio = round((next_area - previous_area) / max(previous_area, 1), 3)
    growth = max(0, round(growth_flp_per_hour / 60 * area_ratio * total_minutes))
    reduction = round(suppression_total * area_ratio)
    active = [d for d in fleet if d.get("uav_id") in selected_ids]
    any_working = any(d.get("status") == "working" for d in active)
    any_agent = any(float(d.get("agent_remaining", 0)) > 0 for d in active)
    if fire_load <= 0:
        action, reason = "finish", "火情负荷已清零，进入效果确认并归档。"
    elif stalled_agent or (active and not any_agent and not stock.get("water_liters")):
        action, reason = "resupply", "药剂或备用电池已耗尽，需要补给/换电后继续。"
    # BE-12：reinforce 判定带绝对下限——余烬级（<20 FLP）火情的 ±3 FLP 波动即超 5%，
    # 相对阈值在清扫阶段噪声误报 reinforce（曾于 6 FLP 时反复触发重规划风暴）
    elif fire_load > load_before * 1.05 and fire_load >= 20.0 and not any_working:
        action, reason = "reinforce", "火势增长快于处置能力，建议请求增援并扩大侦察范围。"
    elif soc_return_risk:
        action, reason = "return", "预计返航 SOC 低于 25%，触发硬约束，部分机组提前返航。"
    else:
        action, reason = "continue", "火势受到抑制，继续当前任务并在 5 分钟后复评。"

    triggers = []
    # BE-12 补：与 add_round 累计触发器同样的绝对下限——余烬级（<20 FLP）的 ±1 FLP
    # 波动即超相对阈值，清扫阶段会每轮触发 wind/replan 风暴（实测 1.9→3.21 触发 v3）
    if fire_load > load_before * 1.2 and fire_load >= 20.0:
        triggers.append("fire_load_increase_over_20_percent")
    if dispatch.get("wind_band") and dispatch["wind_band"].get("band") != band["band"]:
        triggers.append("wind_band_changed")
    if soc_return_risk:
        triggers.append("soc_below_return_threshold")
    if stalled_agent:
        triggers.append("agent_insufficient")
    requested_liters = float(extinguishing_liters or 0)
    water_now = float(stock.get("water_liters", 0))
    # BE-12：缺口口径与 can_control 一致——计入可用且安全水源容量（§5.3 就地取水），
    # 否则出现 can_control=True 但缺口仍报水不足的自相矛盾展示
    water_now += sum(
        float(s.get("capacity_liters", 0) or 0)
        for s in (stock.get("water_sources") or [])
        if s.get("available") and s.get("safe", True))
    return {
        "next_fire_area_m2": next_area,
        "next_fire_load_flp": round(fire_load, 2),
        "fire_load_flp": round(fire_load, 2),
        "fire_load_before_flp": round(load_before, 2),
        "growth_area_m2": growth,
        "extinguished_area_m2": reduction,
        "change_ratio": ratio,
        "action": action, "reason": reason, "trigger_reason": reason,
        "replan_triggers": triggers, "replan_required": bool(triggers),
        "next_check_minutes": 5,
        "wind_band": band,
        "input": {"image_name": image_name if image_name is not None else analysis.get("source_image"), "fleet_snapshot": fleet, "inventory": stock},
        "availability": {"firefighting_drones": available_drones, "water_liters": water_now, "effective_flp": round(suppression_total, 2)},
        # BE-13（评审问题5）：消耗按药剂单位分键——W20 记 water_liters（升）、C6 记
        # co2_kg（千克），禁止再出现「C6 记成水」的混账。
        "resource_consumed": {"water_liters": round(consumed_water, 2), "co2_kg": round(consumed_co2, 2), "module": module},
        "resource_gap": ([{"resource": "water_liters", "required": requested_liters, "available": water_now, "gap": requested_liters - water_now, "resource_gap": True}] if requested_liters > water_now else []),
        # BE-13（评审问题3）：battery_plan 随轮回写相位进度与真实航程，跨轮续接不再丢失
        # outbound_minutes（此前只回 4 个键，下轮航程退化成默认 1/4 分钟）。
        "battery_plan": [
            {
                "uav_id": d["uav_id"], "soc_after": d["soc"], "status": d["status"],
                "agent_remaining": d.get("agent_remaining", 0), "payload_module": d.get("payload_module"),
                "outbound_minutes": round(float(d.get("_outbound_minutes", 0) or 0), 2),
                "phase_elapsed": round(float(d.get("_phase_elapsed", 0) or 0), 2),
                "phase_minutes": round(float(d.get("_phase_minutes", 0) or 0), 2),
            }
            for d in fleet if d.get("uav_id") in selected_ids
        ],
        "emergency_units": emergency_units,
        "emergency_soc_percent": state["emergency_soc"],
        "next_inventory": stock,
        "next_fleet": fleet,
    }

