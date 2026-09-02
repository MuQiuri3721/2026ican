import json
from pathlib import Path
from typing import Any, Dict

from .base import BaseTool, ToolError

ROOT = Path(__file__).resolve().parents[3]

def read_json(path: str) -> Any:
    with (ROOT / path).open(encoding="utf-8") as file:
        return json.load(file)

class DemoTool(BaseTool):
    def __init__(self, name: str, handler, description: str, source: str = "demo-stub"):
        self.name, self._handler, self.description, self.source = name, handler, description, source
    def run(self, **payload):
        return self._handler(**payload)

def not_implemented(**_: Any) -> Dict[str, Any]:
    return {"status": "not_implemented", "message": "真实适配器尚未接入，当前保留接口契约。"}

def get_environment(scene_id: str = "forest-demo-01", **_: Any) -> Dict[str, Any]:
    scene = read_json("data/scene.json")
    if scene["scene_id"] != scene_id:
        raise ToolError("scene_not_found", "未知演示场景")
    return scene

def get_fleet_status(scene_id: str = "forest-demo-01", **_: Any) -> Dict[str, Any]:
    return {"scene_id": scene_id, "fleet": read_json("data/fleet.json")}

def get_inventory(scene_id: str = "forest-demo-01", **_: Any) -> Dict[str, Any]:
    return {"scene_id": scene_id, "inventory": read_json("data/inventory.json")}

def get_water_sources(scene_id: str = "forest-demo-01", max_distance_m: float = 5000, **_: Any) -> Dict[str, Any]:
    scene = get_environment(scene_id)
    return {"sources": [x for x in scene["water_sources"] if x["distance_m"] <= max_distance_m]}

def calculate_wind_vector(wind_speed: float, wind_direction_deg: float, **_: Any) -> Dict[str, float]:
    import math
    angle = math.radians(wind_direction_deg)
    return {"x": round(wind_speed * math.cos(angle), 4), "y": round(wind_speed * math.sin(angle), 4)}

def estimate_growth(area_m2: float, growth_rate: float, wind_speed: float = 0, elapsed_minutes: float = 5, **_: Any) -> Dict[str, float]:
    growth = area_m2 * growth_rate * (1 + 0.04 * wind_speed) * elapsed_minutes / 60
    return {"growth_area_m2": round(growth), "predicted_area_m2": round(area_m2 + growth)}

def calculate_drone_count(resource_liters: float, capacity_liters: float = 80, **_: Any) -> Dict[str, int]:
    import math
    return {"required_drones": max(1, math.ceil(resource_liters / max(capacity_liters, 1)))}

def calculate_distance(origin: Dict[str, float], target: Dict[str, float], speed_mps: float = 10, **_: Any) -> Dict[str, float]:
    import math
    distance = math.hypot(target["x"] - origin["x"], target["y"] - origin["y"])
    return {"distance_m": round(distance, 2), "estimated_minutes": round(distance / max(speed_mps, 0.1) / 60, 2)}

def check_battery(battery_percent: float, required_percent: float, reserve_percent: float = 18, **_: Any) -> Dict[str, Any]:
    return {"valid": battery_percent - required_percent >= reserve_percent, "remaining_percent": battery_percent - required_percent, "reserve_percent": reserve_percent}

def check_payload(payload_liters: float, required_liters: float, **_: Any) -> Dict[str, Any]:
    return {"valid": payload_liters >= required_liters, "available_liters": payload_liters, "required_liters": required_liters}

def build_core_tools():
    handlers = {"extract_frames": not_implemented, "detect_fire": not_implemented, "calculate_fire_metrics": not_implemented, "analyze_visual_trend": not_implemented, "analyze_with_vlm": not_implemented, "get_water_sources": get_water_sources, "calculate_wind_vector": calculate_wind_vector, "predict_spread": not_implemented, "retrieve_scene_knowledge": not_implemented, "assess_fire_level": not_implemented, "estimate_growth": estimate_growth, "match_extinguisher": not_implemented, "calculate_resource_need": not_implemented, "validate_plan": not_implemented, "calculate_drone_count": calculate_drone_count, "assign_tasks": not_implemented, "calculate_distance": calculate_distance, "plan_route": not_implemented, "check_battery": check_battery, "check_payload": check_payload, "execute_firefighting": not_implemented, "resupply": not_implemented, "return_to_charge": not_implemented, "update_fire_state": not_implemented, "evaluate_result": not_implemented, "make_next_decision": not_implemented}
    return [DemoTool(name, handler, "方案定义的可插拔 Tool；未接入能力返回 not_implemented。") for name, handler in handlers.items()]
