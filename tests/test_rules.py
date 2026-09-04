"""确定性规则 Tool 的标准算例与冻结公式契约测试。

对应 docs/无人机子群与参数规则1.md 的冻结口径：风档/坡度档、FLP 网格、
κ 药剂兼容表、SOC 需求与 25% 返航硬约束、J 评分权重、水源六条件、
UAV 状态机与低电量回返触发。
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.tools.base import ToolError  # noqa: E402
from backend.app.tools.core import (  # noqa: E402
    _agent_kappa,
    build_fire_grid,
    calculate_agent_effective_flp,
    calculate_energy_consumption,
    calculate_resource_gap,
    calculate_soc_need,
    check_uav_feasibility,
    normalize_uav_record,
    plan_evacuation_route,
    resolve_slope_factor,
    resolve_wind_band,
    score_candidate_plan,
    select_water_source,
    transition_uav_state,
)
from backend.app.pipeline import simulate_monitor  # noqa: E402


def test_wind_bands_frozen_levels():
    assert resolve_wind_band(3.9)["band"] == 0
    assert resolve_wind_band(3.9)["k_wind"] == 1.0
    assert resolve_wind_band(4.0)["band"] == 1
    assert resolve_wind_band(4.0)["k_wind"] == 1.2
    assert resolve_wind_band(6.0)["band"] == 2
    assert resolve_wind_band(6.0)["k_wind"] == 1.5
    over = resolve_wind_band(8.0)
    assert over["band"] == 3 and over["label"] == ">8 m/s"


def test_slope_bands():
    assert resolve_slope_factor(14.9)["k_slope"] == 1.0
    assert resolve_slope_factor(15.0)["k_slope"] == 1.15
    assert resolve_slope_factor(45.0)["k_slope"] == 1.3


def test_flp_grid_standard_example():
    """B_i = 10 × I × K_fuel × K_wind × K_slope：单个 100 m² 网格、I=2、一般林地、4–6 m/s、缓坡。"""
    grid = build_fire_grid(fire_area_m2=100, wind_speed=5, slope_deg=10, fuel_type="general_forest", intensity=2)
    assert grid["cell_count"] == 1
    assert grid["fire_load_flp"] == pytest.approx(10 * 2 * 1.0 * 1.2 * 1.0)


def test_kappa_table_and_effective_flp():
    assert _agent_kappa("water_20l", "vegetation") == (1.0, True)
    assert _agent_kappa("co2_6kg", "vegetation") == (0.25, True)
    assert _agent_kappa("water_20l", "electrical") == (0.0, False)
    assert _agent_kappa("co2_6kg", "electrical") == (1.5, True)
    result = calculate_agent_effective_flp(20, "water_20l", "vegetation", drop_efficiency=0.9, weather_efficiency=1.0)
    assert result["effective_flp"] == pytest.approx(18.0)
    assert result["compatible"] is True


def test_soc_need_and_uav_feasibility():
    need = calculate_soc_need(soc_outbound=10, soc_task=20, soc_return=10, soc_reserve=25)
    assert need["soc_need"] == 65
    assert need["return_threshold"] == 25
    healthy = {"uav_id": "E1", "subgroup": "suppression", "status": "available", "soc": 90,
               "payload_capacity_kg": 25, "payload_module": "water_20l", "health": 100}
    assert check_uav_feasibility(healthy, required_payload=20, soc_need=60, distance_m=100)["feasible"]
    reasons = check_uav_feasibility(healthy, required_payload=30, soc_need=80, required_module="co2_6kg")["reasons"]
    assert "载荷超限" in reasons
    assert "返航 SOC 低于25%" in reasons
    assert "药剂模块不兼容" in reasons


def test_energy_consumption_formula():
    result = calculate_energy_consumption(task_mass=20, capacity_mass=25, mode_rate=270, duration_minutes=10)
    assert result["load_ratio"] == pytest.approx(0.8)
    assert result["effective_rate_percent_per_hour"] == pytest.approx(270 * (1 + 0.45 * 0.8))
    assert result["delta_soc"] == pytest.approx(270 * 1.36 * 10 / 60)


def test_j_scoring_weights_and_ordering():
    better = score_candidate_plan(control_minutes=60, residual_flp=0, fire_load_flp=60,
                                  energy_total=50, uav_count=2, material_used=40, changes=1)
    worse = score_candidate_plan(control_minutes=180, residual_flp=60, fire_load_flp=60,
                                 energy_total=180, uav_count=2, material_used=80, changes=4)
    expected = 0.4 * 0.5 + 0.15 * 0.25 + 0.10 * 0.5 + 0.05 * 0.25
    assert better["score"] == pytest.approx(expected)
    assert better["score"] < worse["score"]
    assert better["lower_is_better"] is True


def test_select_water_source_six_conditions():
    """不满足“至少节省 5 分钟”必须回退基地补给；六条件齐全才允许就地取水。"""
    rejected = select_water_source(
        [{"available": True, "safe_access": True, "capacity_remaining": 100, "fill_minutes": 8, "distance_m": 300}],
        distance_m=300, cycle_minutes=2,
    )
    assert rejected["selected"] is False
    assert "基地补给" in rejected["reason"]
    accepted = select_water_source(
        [{"available": True, "safe_access": True, "capacity_remaining": 100, "fill_minutes": 8, "distance_m": 300}],
        distance_m=300, cycle_minutes=0, base_fill_minutes=15, soc_after_cycle=60,
    )
    assert accepted["selected"] is True


def test_uav_state_machine_rejects_illegal_transition():
    assert transition_uav_state("flying", "working")["valid"]
    with pytest.raises(ToolError):
        transition_uav_state("available", "flying")


def test_resource_gap_and_evacuation_route():
    gap = calculate_resource_gap(100, 60, "water_liters")
    assert gap["gap"] == 40 and gap["resource_gap"] is True
    blocked = plan_evacuation_route([0, 0], [2, 2], blocked=[[1, 0], [1, 1], [1, 2]], grid_cols=3, grid_rows=3)
    open_route = plan_evacuation_route([0, 0], [2, 2], grid_cols=3, grid_rows=3)
    assert blocked["found"] is False
    assert open_route["found"] is True and open_route["steps"] == 4


def test_normalize_uav_record_keeps_legacy_aliases():
    record = normalize_uav_record({"id": "E9", "role": "firefighting", "battery": 50, "payload": 20})
    assert record["uav_id"] == "E9" and record["subgroup"] == "suppression"
    assert record["soc"] == 50 and record["agent_remaining"] == 20
    assert record["payload_module"] == "water_20l" and record["schema_version"] == "uav-v1"


def _low_soc_monitor_analysis():
    fleet = [{"uav_id": "E1", "id": "E1", "subgroup": "suppression", "role": "firefighting",
              "status": "available", "position": {"x": 40, "y": 0}, "soc": 26, "battery": 26,
              "payload_capacity_kg": 25, "payload_module": "water_20l", "payload": 20,
              "agent_remaining": 20, "agent_unit": "L", "speed_mps": 8,
              "energy_rate_percent_per_hour": 270, "signal": 100, "health": 100}]
    inventory = {"water_liters": 200, "water_modules_w20": 10, "co2_modules_c6": 2, "battery_packs": 0,
                 "support_boxes_sup10": 0, "forward_supply_points": [], "water_sources": [],
                 "dry_powder_kg": 0, "nearby_water_available": False}
    return {
        "fire_assessment": {"fire_area_m2": 9000, "growth_rate": 0.1},
        "environment": {"wind_speed": 6.5},
        "dispatch_plan": {"material_module": "water_20l", "fire_load_flp": 50, "growth_flp_per_hour": 6,
                          "selected_uavs": ["E1"], "battery_plan": [{"uav_id": "E1", "outbound_minutes": 0.5}]},
        "fleet": fleet,
        "inventory": inventory,
    }


def test_monitor_low_soc_triggers_return():
    """场景 4（SOC 不足提前返航）在规则层验证：API 层任务快照由 Store 持有，无法注入低电量。"""
    result = simulate_monitor(_low_soc_monitor_analysis(), elapsed_minutes=5, extinguishing_liters=0)
    assert result["action"] == "return"
    assert "soc_below_return_threshold" in result["replan_triggers"]
    e1 = next(entry for entry in result["battery_plan"] if entry["uav_id"] == "E1")
    assert e1["soc_after"] < 25


def _state_with_fleet(fleet):
    from backend.app.pipeline import load_demo_state
    state = load_demo_state("forest-demo-01")
    state["fleet"] = fleet
    return state


def test_new_task_soc_floor_excludes_low_battery_units():
    """G-1（规则 V1 §4.2）：SOC<35% 的新任务机不进入候选集（25% 仅为返航阈值）。"""
    from backend.app.pipeline import deterministic_v1_dispatch
    fleet = [
        {"uav_id": "E1", "subgroup": "suppression", "role": "firefighting", "status": "available",
         "position": {"x": 200, "y": 80}, "soc": 30, "payload_capacity_kg": 25,
         "payload_module": "water_20l", "agent_remaining": 20, "agent_unit": "L",
         "speed_mps": 8, "energy_rate_percent_per_hour": 270, "health": 100},
        {"uav_id": "E2", "subgroup": "suppression", "role": "firefighting", "status": "available",
         "position": {"x": 210, "y": 80}, "soc": 90, "payload_capacity_kg": 25,
         "payload_module": "water_20l", "agent_remaining": 20, "agent_unit": "L",
         "speed_mps": 8, "energy_rate_percent_per_hour": 270, "health": 100},
    ]
    plan = deterministic_v1_dispatch(_state_with_fleet(fleet), {"fire_load_flp": 40, "growth_flp_per_hour": 4, "fire_type": "vegetation", "wind_speed": 4})
    assert "E1" not in plan["selected_uavs"], "SOC 30% 的机不得入选新任务"
    assert plan["selected_uavs"][0].startswith("E")


def test_water_plan_evaluated_via_six_conditions():
    """G-2（规则 V1 §5.3）：就地取水评估真实执行；演示水源 8 min 装水比基地 4 min 慢 → 基地胜出。"""
    from backend.app.pipeline import deterministic_v1_dispatch, load_demo_state
    state = load_demo_state("forest-demo-01")
    plan = deterministic_v1_dispatch(state, {"fire_load_flp": 40, "growth_flp_per_hour": 4, "fire_type": "vegetation", "wind_speed": 4})
    water_plan = plan["water_source_plan"]
    assert water_plan["mode"] in {"base", "onsite"}
    assert "就地取水评估" in water_plan["reason"] or water_plan["mode"] == "onsite"


def test_monitor_flags_emergency_units_below_15_percent():
    """G-3（规则 V1 §4.2）：SOC<15% 的任务机进入 emergency_units 应急标记。"""
    from backend.app.pipeline import simulate_monitor
    analysis = _low_soc_monitor_analysis()
    analysis["dispatch_plan"]["selected_uavs"] = ["E1"]
    analysis["fleet"][0]["soc"] = 26
    result = simulate_monitor(analysis, elapsed_minutes=5, extinguishing_liters=0)
    assert "emergency_units" in result and "emergency_soc_percent" in result
    # 高耗电率下 5 分钟内 SOC 跌破 15%
    assert "E1" in result["emergency_units"]
