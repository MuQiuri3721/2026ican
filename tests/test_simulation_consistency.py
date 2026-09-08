"""BE-13 · 评审回归测试 1-8（docs/代码更正与执行链路统一方案.md §六）。

验收口径（正确系统不要求火必灭，而要求行为可复现、口径诚实）：
1 时间分段等价：10×1 = 2×5 = 1×10，最终 FLP/SOC/库存完全一致；
2 预测-执行一致：候选预测与正式回放共用 advance_one_minute，时长/水源/换电对齐；
3 W20/C6 隔离：按机自身模块计量，升与千克分键，κ 按本机模块×火型查表；
4 服务计时：基地补水 4min、就地取水 8min、C6 换模块 5min、换电 5min，未完成不作业；
5 空载禁止出动：无药剂可补不得复飞灭火；
6 补位原子性：selected_uavs / firefighting_uavs / battery_plan / tasks / 锁全部同步换人；
7 审批不改变火势：仅 approve 不得改变下一分钟增长；
8 2+6+4 完整场景：上限解锁、不可控时输出真实缺口而非强行成功。
"""
import copy
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend.app.main import app  # noqa: E402
from backend.app.pipeline import (  # noqa: E402
    deterministic_v1_dispatch,
    load_demo_state,
    normalize_fleet,
    normalize_inventory,
    simulate_monitor,
)
from backend.app.agents.backfill import build_candidates  # noqa: E402
from backend.app.rules.engine import simulate_dispatch_candidate  # noqa: E402


# ---------- 公共构造器 ----------

def _drone(uid, module="water_20l", soc=90.0, agent=None, status="available", speed=8.0,
           energy=270.0, multi_role=False, position=None):
    agent = (20.0 if module == "water_20l" else 6.0) if agent is None else agent
    drone = {
        "uav_id": uid, "id": uid,
        "subgroup": "support" if uid.startswith("S") else "suppression",
        "status": status, "soc": soc, "battery": soc, "health": 100,
        "payload_module": module, "agent_remaining": agent, "payload": agent,
        "speed_mps": speed, "energy_rate_percent_per_hour": energy,
        "position": position or {"x": 200, "y": 200},
    }
    if multi_role:
        drone["multi_role"] = True
    return drone


def _inventory(**overrides):
    stock = {
        "water_liters": 480.0, "water_modules_w20": 24, "co2_modules_c6": 4,
        "battery_packs": 48, "support_boxes_sup10": 6,
        "water_sources": [{"name": "紫霞湖水库", "available": True, "safe": True,
                           "capacity_liters": 1200.0, "distance_m": 1100}],
    }
    stock.update(overrides)
    return stock


def _analysis(fleet, fire_load=120.0, module="water_20l", fire_type="vegetation",
              inventory=None, wind=3.0, growth=0.42, outbound=3.0):
    fighters = [d["uav_id"] for d in fleet if d["uav_id"].startswith("E") or d.get("multi_role")]
    return {
        "fire_assessment": {"fire_type": fire_type, "fire_area_m2": fire_load * 5.0,
                            "area_per_flp": 5.0, "growth_rate": growth},
        "environment": {"wind_speed": wind},
        "scene": {"fire_origin": {"x": 400, "y": 300}},
        "fleet": fleet,
        "inventory": inventory or _inventory(),
        "dispatch_plan": {
            "material_module": module, "fire_load_flp": fire_load,
            "firefighting_uavs": fighters, "selected_uavs": fighters,
            "growth_rate_per_hour": growth, "growth_baseline_flp": fire_load,
            "growth_flp_per_hour": round(fire_load * growth, 2),
            "battery_plan": [{"uav_id": uid, "outbound_minutes": outbound} for uid in fighters],
        },
    }


def _drive(analysis, splits, extinguishing=0):
    """按时间分段推进任务，返回每轮 monitor 结果（analysis 原地续接）。"""
    results = []
    for elapsed in splits:
        result = simulate_monitor(analysis, elapsed, extinguishing,
                                  fleet_snapshot=analysis.get("fleet"),
                                  inventory=analysis.get("inventory"))
        analysis["fleet"] = result["next_fleet"]
        analysis["inventory"] = result["next_inventory"]
        analysis["dispatch_plan"] = {**analysis["dispatch_plan"], "fire_load_flp": result["next_fire_load_flp"]}
        results.append(result)
    return results


def _minute_statuses(analysis, minutes):
    """逐分钟推进并返回 (每分钟末全员状态时间线, 全部 monitor 结果)。"""
    statuses, results = [], []
    for _ in range(minutes):
        results.extend(_drive(analysis, [1]))
        statuses.append({d["uav_id"]: d["status"] for d in analysis["fleet"]})
    return statuses, results


def _client() -> TestClient:
    return TestClient(app)


# ---------- 测试 1：时间分段等价 ----------

def test_1_time_partition_equivalence():
    fleet = [_drone("E1"), _drone("E2", soc=84.0), _drone("E3", module="co2_6kg", soc=79.0), _drone("R1", module="none", agent=0.0, speed=12.0, energy=90.0)]
    runs = []
    for splits in ([10], [5, 5], [1] * 10):
        analysis = _analysis(copy.deepcopy(fleet), fire_load=120.0)
        results = _drive(analysis, splits)
        runs.append({
            "flp": results[-1]["next_fire_load_flp"],
            "soc": {d["uav_id"]: d["soc"] for d in analysis["fleet"]},
            "status": {d["uav_id"]: d["status"] for d in analysis["fleet"]},
            "stock": {k: analysis["inventory"].get(k) for k in ("water_liters", "water_modules_w20", "co2_modules_c6", "battery_packs")},
        })
    # FLP 允许轮界量化误差：next_fire_load_flp 按契约 round(,2)，分段边界处引入
    # ≤0.005 的量化（评审测试2 同款"约定时间步长误差"）；SOC/状态/库存必须严格相等
    assert abs(runs[0]["flp"] - runs[1]["flp"]) <= 0.02 and abs(runs[0]["flp"] - runs[2]["flp"]) <= 0.02, [r["flp"] for r in runs]
    assert runs[0]["soc"] == runs[1]["soc"] == runs[2]["soc"]
    assert runs[0]["status"] == runs[1]["status"] == runs[2]["status"]
    assert runs[0]["stock"] == runs[1]["stock"] == runs[2]["stock"]


# ---------- 测试 2：预测-执行一致 ----------

def test_2_prediction_matches_execution():
    state = load_demo_state("forest-demo-01")
    origin = state["scene"].get("fire_origin", {"x": 0, "y": 0})
    candidates = [u for u in normalize_fleet(state["fleet"]) if u["uav_id"] in ("E1", "E2", "E4")]
    prediction = simulate_dispatch_candidate(
        selected=candidates, fire_load_flp=120.0, growth_flp_per_hour=50.4, growth_rate_per_hour=0.42,
        module="water_20l", fire_type="vegetation", origin=origin,
        inventory=state["inventory"], wind_speed=3.0)
    assert prediction["controlled"], prediction

    battery_plan = []
    for unit in candidates:
        pos = unit.get("position") or origin
        minutes = math.hypot(pos.get("x", 0) - origin.get("x", 0), pos.get("y", 0) - origin.get("y", 0)) / max(float(unit.get("speed_mps", 8)), 0.1) / 60
        battery_plan.append({"uav_id": unit["uav_id"], "outbound_minutes": max(0.5, round(minutes, 2))})
    analysis = _analysis(copy.deepcopy(candidates), fire_load=120.0)
    analysis["scene"]["fire_origin"] = origin
    analysis["inventory"] = normalize_inventory(state["inventory"])
    analysis["dispatch_plan"]["battery_plan"] = battery_plan

    minutes_used, water_used = 0, 0.0
    for _ in range(prediction["minutes_used"] + 10):
        result = _drive(analysis, [1])[-1]
        minutes_used += 1
        water_used += result["resource_consumed"]["water_liters"]
        if result["next_fire_load_flp"] <= 0:
            break
    assert (result["next_fire_load_flp"] <= 0) == prediction["controlled"]
    assert abs(minutes_used - prediction["minutes_used"]) <= 1, (minutes_used, prediction["minutes_used"])
    assert abs(water_used - prediction["material_used"]) <= 20.0, (water_used, prediction["material_used"])
    assert sum(int(d.get("_swap_count", 0)) for d in analysis["fleet"]) == prediction["swaps"]
    assert sum(int(d.get("_refill_count", 0)) for d in analysis["fleet"]) == prediction["refills"]
    # 预测不得修改正式状态（传入候选保持原样）
    assert candidates[0].get("status") == "available" and "_phase_elapsed" not in candidates[0]


# ---------- 测试 3：W20 / C6 隔离 ----------

def test_3_w20_c6_isolated_metering():
    # 出航 0.5 分钟：第 1 分钟覆盖飞行并入场，第 2 分钟起作业——6 分钟窗口给足 5 分钟喷洒
    fleet = [_drone("E1", position={"x": 400, "y": 300}), _drone("E3", module="co2_6kg", position={"x": 400, "y": 300})]
    analysis = _analysis(copy.deepcopy(fleet), fire_load=150.0, module="water_20l", fire_type="vegetation", outbound=0.5)
    result = _drive(analysis, [6])[-1]
    consumed = result["resource_consumed"]
    # E1：4 L/min × 5 min = 20 L；E3：1.5 kg/min，6 kg 载荷 4 分钟喷空 → 6 kg
    assert consumed["water_liters"] == pytest.approx(20.0)
    assert consumed["co2_kg"] == pytest.approx(6.0)
    # κ 按本机模块×火型：植被火 水 κ=1.0 / C6 κ=0.25；风 3 m/s → eta=0.9
    assert result["availability"]["effective_flp"] == pytest.approx((20.0 * 1.0 + 6.0 * 0.25) * 0.9)
    # 电气火：水 κ=0 无效果，压制只来自 C6（6×1.5×0.9），但水仍按升如实计量消耗
    analysis = _analysis(copy.deepcopy(fleet), fire_load=150.0, module="co2_6kg", fire_type="electrical", outbound=0.5)
    result = _drive(analysis, [6])[-1]
    assert result["resource_consumed"]["water_liters"] == pytest.approx(20.0)
    assert result["availability"]["effective_flp"] == pytest.approx(6.0 * 1.5 * 0.9)


# ---------- 测试 4：服务计时 ----------

def _servicing_timeline(module, stock_overrides, soc=96.0, minutes=12):
    uid = "E3" if module == "co2_6kg" else "E1"
    fleet = [_drone(uid, module=module, soc=soc, agent=0.0, status="servicing")]
    analysis = _analysis(fleet, module=module, inventory=_inventory(**stock_overrides))
    statuses, results = _minute_statuses(analysis, minutes)
    timeline = [entry[uid] for entry in statuses]
    drone = analysis["fleet"][0]
    agent_at = [next(d for d in r["next_fleet"] if d["uav_id"] == uid)["agent_remaining"] for r in results]
    soc_at = [next(d for d in r["next_fleet"] if d["uav_id"] == uid)["soc"] for r in results]
    return timeline, agent_at, soc_at, drone, analysis["inventory"]


def test_4_service_timings_exact():
    # C6 换模块 5 分钟：第 1-5 分钟 servicing，第 6 分钟复飞（药剂回满 6kg），库存恰扣 1 个模块
    timeline, agents, socs, drone, stock = _servicing_timeline("co2_6kg", {})
    assert timeline[:5] == ["servicing"] * 5 and timeline[5] == "flying", timeline
    assert "working" not in timeline[:5]
    assert stock["co2_modules_c6"] == 3 and agents[5] == pytest.approx(6.0)
    # 基地补水 4 分钟
    timeline, agents, socs, drone, stock = _servicing_timeline("water_20l", {})
    assert timeline[:4] == ["servicing"] * 4 and timeline[4] == "flying", timeline
    assert stock["water_liters"] == pytest.approx(460.0) and stock["water_modules_w20"] == 23
    assert agents[4] == pytest.approx(20.0)
    # 基地无水 → 就地取水 8 分钟（水源容量实扣 20L）
    timeline, agents, socs, _, stock = _servicing_timeline("water_20l", {"water_liters": 0, "water_modules_w20": 0})
    assert timeline[:8] == ["servicing"] * 8 and timeline[8] == "flying", timeline
    assert stock["water_sources"][0]["capacity_liters"] == pytest.approx(1180.0)
    assert agents[8] == pytest.approx(20.0)
    # 标准电池换电 5 分钟（药剂满、仅换电，复飞瞬间 SOC=95）
    fleet = [_drone("E1", soc=60.0, status="servicing")]
    analysis = _analysis(fleet)
    statuses, results = _minute_statuses(analysis, 10)
    timeline = [entry["E1"] for entry in statuses]
    socs = [next(d for d in r["next_fleet"] if d["uav_id"] == "E1")["soc"] for r in results]
    assert timeline[:5] == ["servicing"] * 5 and timeline[5] == "flying", timeline
    assert socs[5] == pytest.approx(95.0)
    assert analysis["inventory"]["battery_packs"] == 47


# ---------- 测试 5：空载禁止重新出动 ----------

def test_5_empty_drone_barred_from_relaunch():
    fleet = [_drone("E3", module="co2_6kg", soc=95.0, agent=0.0, status="returning")]
    analysis = _analysis([*fleet], module="co2_6kg", inventory=_inventory(co2_modules_c6=0))
    statuses, results = _minute_statuses(analysis, 40)
    for entry in statuses:
        assert entry["E3"] not in {"flying", "working"}, entry
    # 停摆标志在转换当轮出现（充电满→待命、或轮界发现空载在册机），不要求末轮恰有
    assert any("agent_insufficient" in r["replan_triggers"] for r in results)
    assert analysis["inventory"]["co2_modules_c6"] == 0  # 无库存不得凭空补给


# ---------- 测试 6：故障补位原子性 ----------

def test_6_backfill_atomic_sync():
    client = _client()
    response = client.post("/api/analyze", json={
        "scene_id": "forest-demo-01", "image_name": "demo.jpg", "environment_mode": "offline",
        "people_status": "absent",
        "scenario": {"fire_origin": {"x": 200, "y": 200}, "fire_area_m2": 900, "growth_rate": 0.2, "uav_failure_round": 2},
    })
    assert response.status_code == 200, response.text
    task_id = response.json()["analysis_id"]
    plan = client.get(f"/api/tasks/{task_id}/plan").json()["plan"]
    approved = client.post(f"/api/tasks/{task_id}/approval", json={"action": "approve", "plan_id": plan["plan_id"]})
    assert approved.status_code == 200, approved.text
    first = client.post(f"/api/tasks/{task_id}/rounds", json={"round": 1, "elapsed_minutes": 5, "extinguishing_liters": 100})
    assert first.status_code == 200, first.text
    second = client.post(f"/api/tasks/{task_id}/rounds", json={"round": 2, "elapsed_minutes": 5, "extinguishing_liters": 100})
    assert second.status_code == 200, second.text

    messages = client.get(f"/api/tasks/{task_id}/agent-messages").json()["items"]
    fault = next(m for m in messages if m["msg_type"] == "UAV_FAULT")
    victim = fault["data"]["faulted"]
    backfill = next(m for m in messages if m["msg_type"] == "BACKFILL")
    choice = backfill["data"]["choice"]
    assert choice and choice != "none", backfill

    new_plan = client.get(f"/api/tasks/{task_id}/plan").json()["plan"]
    report = client.get(f"/api/tasks/{task_id}/report").json()
    live_plan = report["result"]["dispatch_plan"]
    # 原子同步：selected_uavs / firefighting_uavs / tasks / battery_plan 全部换人
    assert victim not in live_plan["selected_uavs"] and choice in live_plan["selected_uavs"]
    assert victim not in live_plan["firefighting_uavs"] and choice in live_plan["firefighting_uavs"]
    assert all(task.get("drone_id") != victim for task in live_plan.get("tasks", []))
    battery_entry = next((e for e in live_plan.get("battery_plan", []) if e["uav_id"] == choice), None)
    assert battery_entry is not None and "outbound_minutes" in battery_entry
    # 候选药剂过滤：C6 任务补位候选只能是 co2_6kg 机
    fleet = normalize_fleet(report["result"]["fleet"])
    c6_pool = build_candidates(fleet, set(), 20.0, module="co2_6kg")
    assert all(u["uav_id"] == "E3" for u in c6_pool["ready_now"] + c6_pool["ready_after"])
    # 载荷+补给门槛（评审问题2/§五）：空载机不得进 ready_now；库存可补才入 ready_after；
    # 既无机上药剂又无库存可补的机整体不具备候选资格
    gated = [
        {"uav_id": "E5", "subgroup": "suppression", "status": "available", "soc": 90, "health": 100,
         "payload_module": "water_20l", "agent_remaining": 0.0},
        {"uav_id": "E6", "subgroup": "suppression", "status": "available", "soc": 90, "health": 100,
         "payload_module": "water_20l", "agent_remaining": 20.0},
    ]
    with_stock = build_candidates(gated, set(), 20.0, module="water_20l",
                                 inventory={"water_liters": 480, "water_modules_w20": 24})
    assert [u["uav_id"] for u in with_stock["ready_now"]] == ["E6"]
    assert [u["uav_id"] for u in with_stock["ready_after"]] == ["E5"]  # 无机上药剂但库存可补 → 补给一轮后出动
    dry = build_candidates(gated, set(), 20.0, module="water_20l",
                           inventory={"water_liters": 0, "water_modules_w20": 0, "water_sources": []})
    # 库存干涸只拦"无机上药剂"的 E5；E6 机上带满剂不受补给条件影响
    assert [u["uav_id"] for u in dry["ready_now"]] == ["E6"]
    assert dry["ready_after"] == []
    # 故障机保持 fault（停止产生处置量）
    victim_drone = next(d for d in report["result"]["fleet"] if d.get("uav_id") == victim)
    assert victim_drone["status"] == "fault"


# ---------- 测试 7：审批不改变火势 ----------

def test_7_approval_does_not_change_fire_growth():
    # 单元口径：approve 触发基线（含被污染的旧键）不影响下一分钟增长
    base = _analysis([_drone("E1"), _drone("E2", soc=84.0)], fire_load=100.0)
    plain = _drive(copy.deepcopy(base), [5])[-1]["next_fire_load_flp"]
    stamped = _analysis([_drone("E1"), _drone("E2", soc=84.0)], fire_load=100.0)
    stamped["dispatch_plan"]["replan_trigger_baseline_flp"] = 100.0
    poisoned = _analysis([_drone("E1"), _drone("E2", soc=84.0)], fire_load=100.0)
    poisoned["dispatch_plan"]["base_fire_load_flp"] = 55.0  # 旧档 approve 盖章残留
    assert _drive(stamped, [5])[-1]["next_fire_load_flp"] == plain
    assert _drive(poisoned, [5])[-1]["next_fire_load_flp"] == plain

    # 服务口径：approve 只盖 replan_trigger_baseline_flp，增长参数原样保留
    client = _client()
    response = client.post("/api/analyze", json={
        "scene_id": "forest-demo-01", "image_name": "demo.jpg", "environment_mode": "offline", "people_status": "absent",
    })
    assert response.status_code == 200, response.text
    task_id = response.json()["analysis_id"]
    before = client.get(f"/api/tasks/{task_id}/plan").json()["plan"]
    rate_before = before.get("growth_rate_per_hour")
    approved = client.post(f"/api/tasks/{task_id}/approval", json={"action": "approve", "plan_id": before["plan_id"]})
    assert approved.status_code == 200, approved.text
    live_plan = client.get(f"/api/tasks/{task_id}/report").json()["result"]["dispatch_plan"]
    assert live_plan["replan_trigger_baseline_flp"] == live_plan["fire_load_flp"]
    assert live_plan.get("growth_rate_per_hour") == rate_before
    assert live_plan.get("growth_baseline_flp") == before.get("growth_baseline_flp")
    assert "base_fire_load_flp" not in live_plan  # 审批不再改写增长分母
    # 执行溯源（评审§二：记录提交版本/机群数量/模式；快照随 result 与 rounds 持久）
    report_data = client.get(f"/api/tasks/{task_id}/report").json()["result"]
    provenance = report_data.get("execution_provenance") or {}
    assert provenance.get("backend_commit") not in (None, "", "unknown"), provenance
    assert provenance.get("fleet_count") == len(report_data.get("fleet") or [])
    assert provenance.get("environment_mode") == "offline"


# ---------- 测试 8：2+6+4 完整场景 ----------

def test_8_fleet_2_6_4_full_scenario():
    state = load_demo_state("forest-demo-01")
    state["fleet"] = normalize_fleet(state["fleet"])
    state["inventory"] = normalize_inventory(state["inventory"])
    fire = {"fire_type": "vegetation", "fire_area_m2": 8000, "fire_load_flp": 600.0,
            "growth_flp_per_hour": 252.0, "growth_rate": 0.42, "wind_speed": 3.0}
    plan = deterministic_v1_dispatch(state, fire, "absent", constraints={"max_drones": 8})
    # 上限解锁：出动可超过 4 架（E3 装载 C6 不入水任务，属按机计量的正确排除）
    assert len(plan["firefighting_uavs"]) > 4, plan["firefighting_uavs"]
    assert "E3" not in plan["firefighting_uavs"]
    # 备选组合出现 5/6 架规模（逐数量枚举生效）
    assert max(len(a["selected_uavs"]) for a in plan["alternative_plan"]) > 4
    # 资源诚实战线：600 FLP 超出净处置能力 → 不可控 + 三态裁决 + 有效 FLP 缺口，不强行成功
    assert plan["can_control"] is False
    assert plan["control_verdict"] in {"maintain_only", "cannot_control"}, plan["control_verdict"]
    assert any(gap.get("resource") == "effective_flp" and gap.get("resource_gap") for gap in plan["resource_gap"])
    # 小火仍然可控（J 评分时间权重主导，组合规模交由评分决定，不强行限定 ≤4）
    small = {"fire_type": "vegetation", "fire_area_m2": 300, "fire_load_flp": 30.0,
             "growth_flp_per_hour": 12.6, "growth_rate": 0.42, "wind_speed": 3.0}
    plan_small = deterministic_v1_dispatch(state, small, "absent", constraints={"max_drones": 8})
    assert plan_small["can_control"] is True
    assert plan_small["control_verdict"] == "can_control"
    assert 1 <= len(plan_small["firefighting_uavs"]) <= 8
