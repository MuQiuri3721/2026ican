import json
import math
from pathlib import Path
from typing import Any, Dict

from .base import BaseTool, ToolError

ROOT = Path(__file__).resolve().parents[3]


def read_json(path: str) -> Any:
    with (ROOT / path).open(encoding="utf-8") as file:
        return json.load(file)


def scene_data(scene_id: str) -> Dict[str, Any]:
    scene = read_json("data/scene.json")
    if scene.get("scene_id") != scene_id:
        raise ToolError("scene_not_found", "未知演示场景", {"scene_id": scene_id})
    return scene


def not_implemented(**_: Any) -> Dict[str, Any]:
    return {"status": "not_implemented", "message": "真实适配器尚未接入，当前保留接口契约。"}


def get_water_sources(scene_id: str = "forest-demo-01", max_distance_m: float = 5000, **_: Any) -> Dict[str, Any]:
    return {"sources": [source for source in scene_data(scene_id)["water_sources"] if source["distance_m"] <= max_distance_m]}


def calculate_wind_vector(wind_speed: float, wind_direction_deg: float, **_: Any) -> Dict[str, float]:
    angle = math.radians(wind_direction_deg)
    return {"x": round(wind_speed * math.cos(angle), 4), "y": round(wind_speed * math.sin(angle), 4)}


def predict_spread(origin: Dict[str, float], wind_vector: Dict[str, float], elapsed_minutes: float = 5, spread_factor: float = 0.1, **_: Any) -> Dict[str, Any]:
    return {"center": {"x": round(origin["x"] + wind_vector["x"] * elapsed_minutes * spread_factor, 4), "y": round(origin["y"] + wind_vector["y"] * elapsed_minutes * spread_factor, 4)}, "direction_vector": wind_vector, "elapsed_minutes": elapsed_minutes}


def estimate_growth(area_m2: float, growth_rate: float, wind_speed: float = 0, elapsed_minutes: float = 5, **_: Any) -> Dict[str, float]:
    growth = area_m2 * growth_rate * (1 + 0.04 * wind_speed) * elapsed_minutes / 60
    return {"growth_area_m2": round(growth), "predicted_area_m2": round(area_m2 + growth)}


def calculate_resource_need(fire_area_m2: float, level_factor: float = 1.0, base_liters_per_m2: float = 0.025, environment_factor: float = 1.15, safety_factor: float = 1.1, target_minutes: float = 18, **_: Any) -> Dict[str, float]:
    total = math.ceil(fire_area_m2 * base_liters_per_m2 * level_factor * environment_factor * safety_factor)
    return {"total_liters": total, "liters_per_minute": round(total / max(target_minutes, 1), 2), "target_minutes": target_minutes}


def calculate_drone_count(resource_liters: float, capacity_liters: float = 80, **_: Any) -> Dict[str, int]:
    return {"required_drones": max(1, math.ceil(resource_liters / max(capacity_liters, 1)))}


def calculate_distance(origin: Dict[str, float], target: Dict[str, float], speed_mps: float = 10, **_: Any) -> Dict[str, float]:
    distance = math.hypot(target["x"] - origin["x"], target["y"] - origin["y"])
    return {"distance_m": round(distance, 2), "estimated_minutes": round(distance / max(speed_mps, 0.1) / 60, 2)}


def plan_route(origin: Dict[str, float], target: Dict[str, float], **_: Any) -> Dict[str, Any]:
    distance = calculate_distance(origin, target)
    return {"waypoints": [origin, target], "distance_m": distance["distance_m"], "estimated_minutes": distance["estimated_minutes"], "risk": "medium", "source": "direct-line-demo"}


def check_battery(battery_percent: float, required_percent: float, reserve_percent: float = 18, **_: Any) -> Dict[str, Any]:
    return {"valid": battery_percent - required_percent >= reserve_percent, "remaining_percent": round(battery_percent - required_percent, 2), "reserve_percent": reserve_percent}


def check_payload(payload_liters: float, required_liters: float, **_: Any) -> Dict[str, Any]:
    return {"valid": payload_liters >= required_liters, "available_liters": payload_liters, "required_liters": required_liters}


def assign_tasks(fleet: list, required_drones: int = 1, **_: Any) -> Dict[str, Any]:
    firefighting = [drone for drone in fleet if drone.get("role") == "firefighting" and drone.get("status") != "offline"]
    selected = sorted(firefighting, key=lambda item: (-item.get("battery", 0), -item.get("payload", 0)))[:required_drones]
    tasks = [{"drone_id": drone["id"], "task": "主力灭火"} for drone in selected]
    return {"tasks": tasks, "assigned_count": len(tasks), "shortfall": max(0, required_drones - len(tasks))}


def update_fire_state(area_m2: float, growth_area_m2: float, extinguished_area_m2: float, **_: Any) -> Dict[str, Any]:
    next_area = max(0, round(area_m2 + growth_area_m2 - extinguished_area_m2))
    return {"area_m2": next_area, "change_ratio": round((next_area - area_m2) / max(area_m2, 1), 3)}


def evaluate_result(previous_area_m2: float, next_area_m2: float, target_area_m2: float = 300, **_: Any) -> Dict[str, Any]:
    reduction = previous_area_m2 - next_area_m2
    return {"score": round(max(0, min(100, 50 + reduction / max(previous_area_m2, 1) * 50)), 1), "target_reached": next_area_m2 <= target_area_m2, "reduction_area_m2": round(reduction)}


def make_next_decision(next_area_m2: float, target_area_m2: float = 300, inventory_liters: float = 0, battery_ok: bool = True, **_: Any) -> Dict[str, str]:
    if next_area_m2 <= target_area_m2: return {"action": "finish", "reason": "火情达到目标阈值。"}
    if not battery_ok: return {"action": "return", "reason": "电量不足，优先返航。"}
    if inventory_liters <= 0: return {"action": "resupply", "reason": "可用物资不足，需要补给。"}
    if next_area_m2 > target_area_m2 * 2: return {"action": "reinforce", "reason": "火情规模仍高于控制阈值，请求增援。"}
    return {"action": "continue", "reason": "当前处置有效，继续灭火并复评。"}


def build_core_tools():
    from .base import FunctionTool
    handlers = {"extract_frames": not_implemented, "detect_fire": not_implemented, "calculate_fire_metrics": not_implemented, "analyze_visual_trend": not_implemented, "analyze_with_vlm": not_implemented, "get_water_sources": get_water_sources, "calculate_wind_vector": calculate_wind_vector, "predict_spread": predict_spread, "retrieve_scene_knowledge": not_implemented, "assess_fire_level": not_implemented, "estimate_growth": estimate_growth, "match_extinguisher": not_implemented, "calculate_resource_need": calculate_resource_need, "validate_plan": not_implemented, "calculate_drone_count": calculate_drone_count, "assign_tasks": assign_tasks, "calculate_distance": calculate_distance, "plan_route": plan_route, "check_battery": check_battery, "check_payload": check_payload, "execute_firefighting": not_implemented, "resupply": not_implemented, "return_to_charge": not_implemented, "update_fire_state": update_fire_state, "evaluate_result": evaluate_result, "make_next_decision": make_next_decision}
    return [FunctionTool(name, handler, "方案定义的可插拔 Tool；未接入能力返回 not_implemented。", "demo-stub") for name, handler in handlers.items()]
