import json
import math
from pathlib import Path
from typing import Any, Dict

from .base import BaseTool, ToolError, FunctionTool

ROOT = Path(__file__).resolve().parents[3]


def read_json(path: str) -> Any:
    with (ROOT / path).open(encoding="utf-8") as file:
        return json.load(file)


def scene_data(scene_id: str = "forest-demo-01") -> Dict[str, Any]:
    scene = read_json("data/scene.json")
    if scene.get("scene_id") != scene_id:
        raise ToolError("scene_not_found", "未知演示场景", {"scene_id": scene_id})
    return scene


def positive(value: float, name: str) -> float:
    if value < 0:
        raise ToolError("invalid_input", name + " 不能为负数")
    return value


def not_implemented(**_: Any) -> Dict[str, Any]:
    return {"status": "not_implemented", "message": "真实适配器尚未接入，当前保留接口契约。"}


def get_water_sources(scene_id: str = "forest-demo-01", max_distance_m: float = 5000, **_: Any) -> Dict[str, Any]:
    positive(max_distance_m, "max_distance_m")
    return {"sources": [source for source in scene_data(scene_id)["water_sources"] if source["distance_m"] <= max_distance_m]}


def calculate_wind_vector(wind_speed: float, wind_direction_deg: float, **_: Any) -> Dict[str, float]:
    positive(wind_speed, "wind_speed")
    angle = math.radians(wind_direction_deg)
    return {"x": round(wind_speed * math.cos(angle), 4), "y": round(wind_speed * math.sin(angle), 4)}


def predict_spread(origin: Dict[str, float], wind_vector: Dict[str, float], elapsed_minutes: float = 5, spread_factor: float = 0.1, **_: Any) -> Dict[str, Any]:
    positive(elapsed_minutes, "elapsed_minutes")
    return {"center": {"x": round(origin["x"] + wind_vector["x"] * elapsed_minutes * spread_factor, 4), "y": round(origin["y"] + wind_vector["y"] * elapsed_minutes * spread_factor, 4)}, "direction_vector": wind_vector, "elapsed_minutes": elapsed_minutes}


def assess_fire_level(fire_area_m2: float, smoke_area_m2: float, wind_speed: float, growth_rate: float, reference_fire_area_m2: float = 2500, reference_smoke_area_m2: float = 6500, reference_wind_speed_mps: float = 12, weights: Dict[str, float] = None, thresholds: list = None, **_: Any) -> Dict[str, Any]:
    values = [fire_area_m2, smoke_area_m2, wind_speed, growth_rate]
    if any(value < 0 for value in values):
        raise ToolError("invalid_input", "火情指标不能为负数")
    weights = weights or {"fire_area": 0.45, "smoke_area": 0.2, "wind_speed": 0.2, "growth_rate": 0.15}
    thresholds = thresholds or [0.3, 0.6, 0.8]
    score = weights["fire_area"] * min(fire_area_m2 / reference_fire_area_m2, 1) + weights["smoke_area"] * min(smoke_area_m2 / reference_smoke_area_m2, 1) + weights["wind_speed"] * min(wind_speed / reference_wind_speed_mps, 1) + weights["growth_rate"] * min(growth_rate, 1)
    level = 1 + sum(score >= threshold for threshold in thresholds)
    return {"level": level, "label": {1: "I 级 · 低风险", 2: "II 级 · 中等火情", 3: "III 级 · 高风险", 4: "IV 级 · 极高风险"}[level], "fire_area_m2": fire_area_m2, "smoke_area_m2": smoke_area_m2, "growth_rate": growth_rate, "risk_score": round(score, 3), "confidence": 0.91, "source": "rules"}


def estimate_growth(area_m2: float, growth_rate: float, wind_speed: float = 0, elapsed_minutes: float = 5, **_: Any) -> Dict[str, float]:
    positive(area_m2, "area_m2"); positive(growth_rate, "growth_rate"); positive(wind_speed, "wind_speed"); positive(elapsed_minutes, "elapsed_minutes")
    growth = area_m2 * growth_rate * (1 + 0.04 * wind_speed) * elapsed_minutes / 60
    return {"growth_area_m2": round(growth), "predicted_area_m2": round(area_m2 + growth)}


def match_extinguisher(fire_type: str = "forest", water_available: bool = True, inventory_liters: float = 0, **_: Any) -> Dict[str, Any]:
    positive(inventory_liters, "inventory_liters")
    material = "water" if water_available and inventory_liters > 0 else "dry_powder"
    return {"material": material, "reason": "附近水源可用，优先取水" if material == "water" else "水源不可用或库存不足，切换干粉", "source": "rules"}


def calculate_resource_need(fire_area_m2: float, level_factor: float = 1.0, base_liters_per_m2: float = 0.025, environment_factor: float = 1.15, safety_factor: float = 1.1, target_minutes: float = 18, **_: Any) -> Dict[str, float]:
    positive(fire_area_m2, "fire_area_m2"); positive(level_factor, "level_factor")
    total = math.ceil(fire_area_m2 * base_liters_per_m2 * level_factor * environment_factor * safety_factor)
    return {"total_liters": total, "liters_per_minute": round(total / max(target_minutes, 1), 2), "target_minutes": target_minutes, "source": "rules"}


def validate_plan(tasks: list, fleet: list, required_liters: float = 0, **_: Any) -> Dict[str, Any]:
    ids = {drone["id"] for drone in fleet}
    task_ids = [task.get("drone_id") for task in tasks]
    errors = ["任务引用了不存在的无人机"] if any(drone_id not in ids for drone_id in task_ids) else []
    if len(task_ids) != len(set(task_ids)): errors.append("同一无人机不能重复分配")
    return {"valid": not errors, "errors": errors, "task_count": len(tasks), "required_liters": required_liters}


def calculate_drone_count(resource_liters: float, capacity_liters: float = 80, available_count: int = 1, **_: Any) -> Dict[str, Any]:
    positive(resource_liters, "resource_liters"); positive(capacity_liters, "capacity_liters")
    required = max(1, math.ceil(resource_liters / capacity_liters))
    return {"required_drones": required, "available_count": available_count, "shortfall": max(0, required - available_count)}


def calculate_distance(origin: Dict[str, float], target: Dict[str, float], speed_mps: float = 10, **_: Any) -> Dict[str, float]:
    positive(speed_mps, "speed_mps")
    distance = math.hypot(target["x"] - origin["x"], target["y"] - origin["y"])
    return {"distance_m": round(distance, 2), "estimated_minutes": round(distance / speed_mps / 60, 2)}


def plan_route(origin: Dict[str, float], target: Dict[str, float], risk: str = "medium", **_: Any) -> Dict[str, Any]:
    distance = calculate_distance(origin, target)
    return {"waypoints": [origin, target], **distance, "risk": risk, "source": "direct-line-demo"}


def check_battery(battery_percent: float, required_percent: float, reserve_percent: float = 18, **_: Any) -> Dict[str, Any]:
    if min(battery_percent, required_percent, reserve_percent) < 0: raise ToolError("invalid_input", "电量参数不能为负数")
    return {"valid": battery_percent - required_percent >= reserve_percent, "remaining_percent": round(battery_percent - required_percent, 2), "reserve_percent": reserve_percent}


def check_payload(payload_liters: float, required_liters: float, **_: Any) -> Dict[str, Any]:
    return {"valid": payload_liters >= required_liters, "available_liters": payload_liters, "required_liters": required_liters}


def assign_tasks(fleet: list, required_drones: int = 1, **_: Any) -> Dict[str, Any]:
    candidates = [drone for drone in fleet if drone.get("role") == "firefighting" and drone.get("status") != "offline"]
    selected = sorted(candidates, key=lambda item: (-item.get("battery", 0), -item.get("payload", 0)))[:required_drones]
    return {"tasks": [{"drone_id": drone["id"], "task": "主力灭火"} for drone in selected], "assigned_count": len(selected), "shortfall": max(0, required_drones - len(selected))}


def execute_firefighting(area_m2: float, extinguishing_liters: float, efficiency: float = 0.9, **_: Any) -> Dict[str, Any]:
    positive(area_m2, "area_m2"); positive(extinguishing_liters, "extinguishing_liters")
    reduced = min(area_m2, round(extinguishing_liters * efficiency))
    return {"remaining_area_m2": area_m2 - reduced, "extinguished_area_m2": reduced, "consumed_liters": extinguishing_liters, "status": "simulated"}


def resupply(current_liters: float, supply_liters: float, capacity_liters: float = 120, **_: Any) -> Dict[str, Any]:
    updated = min(capacity_liters, current_liters + supply_liters)
    return {"current_liters": updated, "added_liters": updated - current_liters, "status": "resupply_simulated"}


def return_to_charge(battery_percent: float, return_distance_m: float, speed_mps: float = 10, consumption_percent_per_minute: float = 1.5, **_: Any) -> Dict[str, Any]:
    travel = calculate_distance({"x": 0, "y": 0}, {"x": return_distance_m, "y": 0}, speed_mps)
    remaining = max(0, battery_percent - travel["estimated_minutes"] * consumption_percent_per_minute)
    return {"estimated_minutes": travel["estimated_minutes"], "remaining_battery_percent": round(remaining, 1), "status": "return_simulated"}


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
    handlers = {"extract_frames": not_implemented, "detect_fire": not_implemented, "calculate_fire_metrics": not_implemented, "analyze_visual_trend": not_implemented, "analyze_with_vlm": not_implemented, "get_water_sources": get_water_sources, "calculate_wind_vector": calculate_wind_vector, "predict_spread": predict_spread, "retrieve_scene_knowledge": not_implemented, "assess_fire_level": assess_fire_level, "estimate_growth": estimate_growth, "match_extinguisher": match_extinguisher, "calculate_resource_need": calculate_resource_need, "validate_plan": validate_plan, "calculate_drone_count": calculate_drone_count, "assign_tasks": assign_tasks, "calculate_distance": calculate_distance, "plan_route": plan_route, "check_battery": check_battery, "check_payload": check_payload, "execute_firefighting": execute_firefighting, "resupply": resupply, "return_to_charge": return_to_charge, "update_fire_state": update_fire_state, "evaluate_result": evaluate_result, "make_next_decision": make_next_decision}
    return [FunctionTool(name, handler, "方案定义的可插拔 Tool；未接入模型的视觉能力返回 not_implemented。", "rules" if handler is not not_implemented else "demo-stub") for name, handler in handlers.items()]
