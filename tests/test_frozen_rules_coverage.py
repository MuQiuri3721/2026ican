"""BE-14 · 冻结规则文档（docs/无人机子群与参数规则1.md）欠账逐条验收。

每条对应「实现对照表」中已闭合的条目：
§5.3 六条件规划层真实评估 / §5.2 余水退库守恒 / §9 S1-S2 分工·通道保留·unknown 限投
§2.2/§8.3 R2 高风险复核·R 在线保障 / §10 通信阈值关键事件 / §4.2 降级带补位
"""
import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.agents.backfill import build_candidates  # noqa: E402
from backend.app.pipeline import (  # noqa: E402
    deterministic_v1_dispatch,
    load_demo_state,
    normalize_fleet,
    normalize_inventory,
    simulate_monitor,
)
from backend.app.rules.engine import _evaluate_water_plan  # noqa: E402


def _state():
    state = load_demo_state("forest-demo-01")
    state["fleet"] = normalize_fleet(state["fleet"])
    state["inventory"] = normalize_inventory(state["inventory"])
    return state


def _fire(area=300, load=None, level=None, growth=0.42):
    load = load if load is not None else area / 10.0
    fire = {"fire_type": "vegetation", "fire_area_m2": area, "fire_load_flp": load,
            "growth_flp_per_hour": round(load * growth, 2), "growth_rate": growth, "wind_speed": 3.0}
    if level is not None:
        fire["level"] = level
    return fire


# ---------- §5.3 六条件真实评估 ----------

def test_water_plan_six_conditions_real_evaluation():
    state = _state()
    # 现场景：六条件逐项给出真实判定；水源比基地远 → 无节省 → 基地补给（诚实理由）
    plan = _evaluate_water_plan(state["scene"], state["inventory"], base_distance_m=830.0)
    assert plan["mode"] == "base"
    assert plan["checks"]["available"] and plan["checks"]["safe_access"] and plan["checks"]["capacity_ge_20l"]
    assert not plan["checks"]["saving_ge_5min"] and plan["saving_minutes"] < 0
    assert "saving_ge_5min" in plan["reason"]
    # 几何有利（基地远、水源近）：节省 ≥5min 且循环后 SOC 达标 → 就地取水可达
    inventory = dict(state["inventory"], water_sources=[
        {"name": "近水源", "available": True, "safe": True, "capacity_liters": 1200, "distance_m": 300}])
    onsite = _evaluate_water_plan(state["scene"], inventory, base_distance_m=2500.0)
    assert onsite["mode"] == "onsite" and onsite["saving_minutes"] >= 5.0
    assert onsite["soc_after_cycle"] >= 25.0


# ---------- §5.2 余水退库守恒 ----------

def test_unused_agent_returns_to_stock():
    analysis = {
        "fire_assessment": {"fire_type": "vegetation", "fire_area_m2": 1500, "area_per_flp": 5.0, "growth_rate": 0.2},
        "environment": {"wind_speed": 3.0},
        "scene": {"fire_origin": {"x": 400, "y": 300}},
        "fleet": [{"uav_id": "E1", "id": "E1", "subgroup": "suppression", "status": "available",
                   "soc": 95.0, "battery": 95.0, "health": 100, "payload_module": "water_20l",
                   "agent_remaining": 20.0, "payload": 20.0, "speed_mps": 8,
                   "energy_rate_percent_per_hour": 270, "position": {"x": 398, "y": 300}}],
        "inventory": {"water_liters": 480.0, "water_modules_w20": 24, "co2_modules_c6": 4,
                      "battery_packs": 48, "water_sources": []},
        "dispatch_plan": {"material_module": "water_20l", "fire_load_flp": 60.0,
                          "firefighting_uavs": ["E1"], "selected_uavs": ["E1"],
                          "growth_rate_per_hour": 0.2, "growth_baseline_flp": 60.0,
                          "growth_flp_per_hour": 12.0,
                          "battery_plan": [{"uav_id": "E1", "outbound_minutes": 0.5}]},
    }
    sprayed_total, water_now, refills = 0.0, None, 0
    # 跑到 E1 完成「喷 5L → 返航 → 落场退 15L → 补 20L」整循环。
    # extinguishing_liters 是「单次监测窗口内」的绝对上限（每次调用 consumed 清零），
    # 所以首拍给 6 分钟+上限 5L（1 分钟入场 + 2 分钟喷 5L + 转（返）航），此后逐分钟推进。
    for i in range(30):
        result = simulate_monitor(analysis, 6 if i == 0 else 1, 5,
                                  fleet_snapshot=analysis["fleet"], inventory=analysis["inventory"])
        analysis["fleet"] = result["next_fleet"]
        analysis["inventory"] = result["next_inventory"]
        analysis["dispatch_plan"]["fire_load_flp"] = result["next_fire_load_flp"]
        sprayed_total += result["resource_consumed"]["water_liters"]
        water_now = analysis["inventory"]["water_liters"]
        refills = sum(int(d.get("_refill_count", 0)) for d in analysis["fleet"])
        if refills >= 1:
            break
    assert refills >= 1
    # 守恒：库存净扣 = 实际喷洒（落场余 15L 先退库再补 20L，净 −5L）
    assert abs(sprayed_total - 5.0) < 0.01, sprayed_total
    assert abs(water_now - (480.0 - sprayed_total)) < 0.01, (water_now, sprayed_total)


# ---------- §9 编组分工 ----------

def test_support_pair_and_roles():
    state = _state()
    plan = deterministic_v1_dispatch(state, _fire(), "unknown", constraints={"max_drones": 4})
    s_ids = [u for u in plan["selected_uavs"] if u.startswith("S")]
    assert s_ids == ["S1", "S2"]
    roles = {t["drone_id"]: t["task"] for t in plan["tasks"] if t["drone_id"].startswith("S")}
    assert roles["S1"] == "复核人员与后备侦察" and roles["S2"] == "通信中继待命"
    confirmed = deterministic_v1_dispatch(state, _fire(), "confirmed", constraints={"max_drones": 4})
    roles_c = {t["drone_id"]: t["task"] for t in confirmed["tasks"] if t["drone_id"].startswith("S")}
    assert roles_c["S1"] == "通信广播/疏散引导" and roles_c["S2"] == "照明与疏散路线复核"


def test_corridor_guard_reserve_when_people_confirmed():
    state = _state()
    plan = deterministic_v1_dispatch(state, _fire(), "confirmed", constraints={"max_drones": 4})
    guard = [t for t in plan["tasks"] if t.get("branch") == "corridor_guard"]
    assert len(guard) == 1
    assert guard[0]["drone_id"] in plan["selected_uavs"]          # 在出动名单（随队待命）
    assert guard[0]["drone_id"] not in plan["firefighting_uavs"]  # 不投入压制组合
    # 无人分支不保留
    plan_absent = deterministic_v1_dispatch(state, _fire(), "absent", constraints={"max_drones": 4})
    assert not [t for t in plan_absent["tasks"] if t.get("branch") == "corridor_guard"]


def test_unknown_people_caps_launch_below_full_strength():
    state = _state()
    state["fleet"] = [u for u in state["fleet"] if u["uav_id"] in ("R1", "S1", "E1", "E2", "E4")]
    fire = _fire(area=8000, load=600.0)
    plan = deterministic_v1_dispatch(state, fire, "unknown", constraints={"max_drones": 3})
    assert len(plan["firefighting_uavs"]) <= 2  # 3 架可战、人员不确定 → 至少留 1 架机动


# ---------- §2.2/§8.3 侦察编组与在线保障 ----------

def test_r2_joins_review_on_high_level_fire():
    state = _state()
    plan = deterministic_v1_dispatch(state, _fire(area=3000, load=900.0, level=3), "absent", constraints={"max_drones": 8})
    r_ids = [u for u in plan["selected_uavs"] if u.startswith("R")]
    assert r_ids == ["R1", "R2"]
    assert any(t["task"] == "高风险复核侦察" and t["drone_id"] == "R2" for t in plan["tasks"])
    plan_low = deterministic_v1_dispatch(state, _fire(level=1), "absent", constraints={"max_drones": 4})
    assert [u for u in plan_low["selected_uavs"] if u.startswith("R")] == ["R1"]


def test_recon_never_both_charging():
    fleet = [
        {"uav_id": "R1", "id": "R1", "subgroup": "reconnaissance", "status": "available", "soc": 46.0,
         "health": 100, "payload_module": "none", "agent_remaining": 0.0, "speed_mps": 12,
         "energy_rate_percent_per_hour": 90, "position": {"x": 0, "y": 0}},
        {"uav_id": "R2", "id": "R2", "subgroup": "reconnaissance", "status": "available", "soc": 46.0,
         "health": 100, "payload_module": "none", "agent_remaining": 0.0, "speed_mps": 12,
         "energy_rate_percent_per_hour": 90, "position": {"x": 0, "y": 0}},
    ]
    analysis = {
        "fire_assessment": {"fire_type": "vegetation", "fire_area_m2": 900, "area_per_flp": 5.0, "growth_rate": 0.1},
        "environment": {"wind_speed": 3.0}, "scene": {"fire_origin": {"x": 0, "y": 0}},
        "fleet": fleet, "inventory": {"water_liters": 480, "battery_packs": 48},
        "dispatch_plan": {"material_module": "water_20l", "fire_load_flp": 50.0,
                          "firefighting_uavs": [], "selected_uavs": ["R1"],
                          "growth_rate_per_hour": 0.1, "growth_baseline_flp": 50.0, "battery_plan": []},
    }
    for _ in range(80):
        result = simulate_monitor(analysis, 1, 0, fleet_snapshot=analysis["fleet"], inventory=analysis["inventory"])
        analysis["fleet"] = result["next_fleet"]
        analysis["inventory"] = result["next_inventory"]
        states = {d["uav_id"]: d["status"] for d in analysis["fleet"]}
        assert not (states["R1"] == "charging" and states["R2"] == "charging"), states
        assert states["R1"] in {"available", "flying", "working", "charging"} or states["R2"] in {"available", "flying", "working"}


# ---------- §10 通信阈值关键事件 ----------

def test_weak_signal_triggers_event():
    analysis = {
        "fire_assessment": {"fire_type": "vegetation", "fire_area_m2": 900, "area_per_flp": 5.0, "growth_rate": 0.1},
        "environment": {"wind_speed": 3.0}, "scene": {"fire_origin": {"x": 0, "y": 0}},
        "fleet": [{"uav_id": "E1", "id": "E1", "subgroup": "suppression", "status": "working", "soc": 80.0,
                   "health": 100, "payload_module": "water_20l", "agent_remaining": 20.0,
                   "speed_mps": 8, "energy_rate_percent_per_hour": 270, "signal": 42.0,
                   "position": {"x": 398, "y": 300}}],
        "inventory": {"water_liters": 480, "battery_packs": 48},
        "dispatch_plan": {"material_module": "water_20l", "fire_load_flp": 50.0,
                          "firefighting_uavs": ["E1"], "selected_uavs": ["E1"],
                          "growth_rate_per_hour": 0.1, "growth_baseline_flp": 50.0,
                          "battery_plan": [{"uav_id": "E1", "outbound_minutes": 0.5}]},
    }
    result = simulate_monitor(analysis, 1, 0)
    assert "signal_below_threshold" in result["replan_triggers"]


# ---------- §4.2 降级带补位 ----------

def test_degraded_soc_band_eligible_for_ready_after():
    gated = [{"uav_id": "E5", "subgroup": "suppression", "status": "available", "soc": 30.0,
              "health": 100, "payload_module": "water_20l", "agent_remaining": 20.0}]
    pool = build_candidates(gated, set(), 20.0, module="water_20l",
                            inventory={"water_liters": 480, "water_modules_w20": 24})
    assert pool["ready_now"] == []                       # 30% 不接主任务（35% 接单线）
    assert [u["uav_id"] for u in pool["ready_after"]] == ["E5"]  # 降级带可补给一轮后补位
    below = build_candidates([dict(gated[0], soc=20.0)], set(), 20.0, module="water_20l")
    assert below["ready_now"] == [] and below["ready_after"] == []  # <25% 返航线，两档都不收
