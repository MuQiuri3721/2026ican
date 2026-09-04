"""算法与地图实景专项测试（追踪清单 SK-2/SK-4）。

覆盖：全部注册 Tool 的执行冒烟、核心 Skill 链（含真实火点航线与疏散分支）、
紫金山真实 DEM 等高线（rasterio 可用时）。
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.tools.registry import build_registry  # noqa: E402
from backend.app.skills.orchestrator import SkillOrchestrator  # noqa: E402
from backend.app.skills.registry import build_skill_registry  # noqa: E402
from backend.app.pipeline import load_demo_state  # noqa: E402


def _valid_uav() -> dict:
    return {"uav_id": "E1", "id": "E1", "subgroup": "suppression", "role": "firefighting",
            "status": "available", "position": {"x": 160, "y": 100}, "soc": 90, "battery": 90,
            "payload_capacity_kg": 25, "payload_module": "water_20l", "payload": 20,
            "agent_remaining": 20, "agent_unit": "L", "speed_mps": 8,
            "energy_rate_percent_per_hour": 270, "signal": 90, "health": 100}


# 必填参数工具的最小合法载荷；其余 Tool 依赖默认值即可执行。
REQUIRED_PAYLOADS = {
    "calculate_fire_metrics": {"detections": [], "image_width": 640, "image_height": 480},
    "validate_plan": {"tasks": [{"drone_id": "E1"}], "fleet": [_valid_uav()], "required_liters": 0},
    "assign_tasks": {"fleet": [_valid_uav()], "required_drones": 1},
    "calculate_distance": {"origin": {"x": 0, "y": 0}, "target": {"x": 3, "y": 4}},
    "plan_route": {"origin": {"x": 0, "y": 0}, "target": {"x": 3, "y": 4}},
    "check_payload": {"payload_liters": 20, "required_liters": 10},
    "transition_uav_state": {"current_state": "available", "next_state": "assigned"},
    "normalize_uav_record": {"record": _valid_uav()},
    "check_uav_feasibility": {"uav": _valid_uav(), "required_payload": 20, "soc_need": 60},
    "assess_fire_level": {"fire_area_m2": 1000, "smoke_area_m2": 2000, "wind_speed": 5, "growth_rate": 0.3},
    "update_fire_state": {"area_m2": 1000, "growth_area_m2": 50, "extinguished_area_m2": 100},
    "evaluate_result": {"previous_area_m2": 1000, "next_area_m2": 900},
    "make_next_decision": {"next_area_m2": 900},
    "execute_firefighting": {"area_m2": 1000, "extinguishing_liters": 40},
    "resupply": {"current_liters": 20, "supply_liters": 20},
    "return_to_charge": {"battery_percent": 50, "return_distance_m": 500},
    "simulate_fire_round": {"fire_load_flp": 60, "suppression_flp": 16},
    "estimate_growth": {"area_m2": 1000, "growth_rate": 0.3},
    "calculate_resource_need": {"fire_area_m2": 1000},
    "calculate_agent_effective_flp": {"agent_quantity": 20},
    "simulate_supply_cycle": {"agent_start": 20},
    "check_battery": {"battery_percent": 90, "required_percent": 40},
    "calculate_drone_count": {"resource_liters": 80},
    "calculate_wind_vector": {"wind_speed": 5, "wind_direction_deg": 315},
    "predict_spread": {"origin": {"x": 0, "y": 0}, "wind_vector": {"x": 3, "y": 4}},
    "build_fire_grid": {"fire_area_m2": 1000},
    "charge_battery": {"soc": 50, "minutes": 30},
    "calculate_resource_gap": {"required": 100, "available": 60},
    "calculate_soc_need": {"soc_outbound": 10, "soc_task": 20, "soc_return": 10},
    "score_candidate_plan": {"control_minutes": 60, "residual_flp": 0, "fire_load_flp": 60,
                             "energy_total": 50, "uav_count": 2, "material_used": 40, "changes": 1},
}


def test_every_registered_tool_executes_with_valid_envelope():
    registry = build_registry()
    assert len(registry.list()) >= 50
    for name in registry.list():
        result = registry.execute(name, REQUIRED_PAYLOADS.get(name, {}))
        assert isinstance(result, dict), name
        assert result.get("tool") == name, name
        assert "ok" in result and "source" in result, name


def test_core_tools_all_succeed():
    registry = build_registry()
    for name in registry.list():
        result = registry.execute(name, REQUIRED_PAYLOADS.get(name, {}))
        assert result.get("ok") is True, f"{name}: {result.get('error')}"


def test_full_skill_chain_uses_real_fire_origin():
    state = load_demo_state("forest-demo-01")
    origin = state["scene"]["fire_origin"]
    orchestrator = SkillOrchestrator(build_skill_registry())
    result = orchestrator.run_analysis({
        "scene_id": "forest-demo-01", "image_name": "demo.jpg",
        "environment_mode": "offline", "people_status": "confirmed",
    })
    chain = result["skill_chain"]
    assert set(orchestrator.CORE_ORDER) <= set(chain), "核心 12 步 Skill 链必须完整执行"

    candidate = chain["candidate_generation"]
    assert candidate["fire_origin"] == origin

    route = chain["route_planning"]["route"]["data"]
    assert route["waypoints"][1] == origin, "航线目标必须是真实火点"
    assert route["distance_m"] > 0


def test_evacuation_skill_plans_route_around_fire():
    orchestrator = SkillOrchestrator(build_skill_registry())
    state = load_demo_state("forest-demo-01")
    context = {
        "people_status": "confirmed",
        "fire_perception": {"observation": {"fire_area_m2": 1800}},
        "candidate_generation": {"fire_origin": state["scene"]["fire_origin"], "v1_dispatch": {}},
    }
    result = orchestrator.run("evacuation", context)
    assert result["status"] == "ok"
    assert result["found"] is True
    assert result["risk_cells"] > 0
    assert result["path"][0] == result["start"]
    assert result["estimated_minutes"] > 0


def test_terrain_contours_on_real_zijin_mountain():
    """默认坐标即紫金山主峰：真实 DEM 下应出现 300m+ 等高线（SK-1 验收）。"""
    pytest.importorskip("rasterio")
    from backend.app.services.terrain_service import generate_contours
    result = generate_contours()
    assert result["status"] == "ok" and result["source"] == "N32E118.hgt"
    elevations = {feature["properties"]["elevation_m"] for feature in result["features"]}
    assert any(level >= 300 for level in elevations), f"紫金山主峰周边应有 300m+ 等高线，实际 {sorted(elevations)}"
    for feature in result["features"]:
        for lon, lat in feature["geometry"]["coordinates"]:
            assert 118.7 <= lon <= 119.0 and 32.0 <= lat <= 32.2


def test_confirmed_people_chain_includes_evacuation():
    """G-4（规则 V1 §9）：确认有人时疏散分支进入核心链并输出可行路线。"""
    orchestrator = SkillOrchestrator(build_skill_registry())
    result = orchestrator.run_analysis({
        "scene_id": "forest-demo-01", "image_name": "demo.jpg",
        "environment_mode": "offline", "people_status": "confirmed",
    })
    chain = result["skill_chain"]
    evacuation = chain.get("evacuation")
    assert evacuation, "确认有人时核心链必须包含疏散分支"
    assert evacuation["found"] is True and evacuation["estimated_minutes"] > 0
