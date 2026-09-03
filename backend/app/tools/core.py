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


def demo_observation(image_name: str = "default", image_path: str = None, **_: Any) -> Dict[str, Any]:
    observations = read_json("data/vision_observations.json")
    key = "small-fire" if image_name and "small" in image_name.lower() else "default"
    observation = dict(observations[key])
    observation.update({"image_name": image_name, "image_path": image_path, "mode": "demo", "source": "vision-observation-fixture"})
    return observation


def calculate_fire_metrics(detections: list, image_width: int, image_height: int, area_scale: float = 0.018, **_: Any) -> Dict[str, Any]:
    if image_width <= 0 or image_height <= 0:
        raise ToolError("invalid_input", "图片尺寸必须大于 0")
    fire_pixels = smoke_pixels = 0
    for detection in detections:
        box = detection.get("box", [])
        if len(box) != 4: continue
        pixels = max(0, box[2] - box[0]) * max(0, box[3] - box[1])
        if detection.get("class_name") == "fire": fire_pixels += pixels
        if detection.get("class_name") == "smoke": smoke_pixels += pixels
    return {"fire_area_m2": round(fire_pixels * area_scale, 2), "smoke_area_m2": round(smoke_pixels * area_scale, 2), "fire_pixels": fire_pixels, "smoke_pixels": smoke_pixels, "source": "demo-metric"}


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


# ----------------------------- V1 deterministic rules -----------------------------

def normalize_uav_record(record: Dict[str, Any], **_: Any) -> Dict[str, Any]:
    """Normalize legacy fleet fields while keeping legacy aliases in the response."""
    item = dict(record or {})
    item["uav_id"] = item.get("uav_id", item.get("id"))
    item["subgroup"] = item.get("subgroup", item.get("role"))
    if item["subgroup"] == "firefighting":
        item["subgroup"] = "suppression"
    item["soc"] = item.get("soc", item.get("battery", 0))
    item["agent_remaining"] = item.get("agent_remaining", item.get("payload", 0))
    if not item.get("agent_unit"):
        item["agent_unit"] = "L" if item.get("payload_module") == "water_20l" else "kg"
    if not item.get("payload_module"):
        item["payload_module"] = {"firefighting": "water_20l"}.get(item.get("role"), "none")
    if not item.get("status"):
        item["status"] = "available"
    if not item["uav_id"] or item["subgroup"] not in {"reconnaissance", "suppression", "support"}:
        raise ToolError("invalid_input", "UAV 缺少合法 uav_id 或 subgroup")
    if not 0 <= float(item["soc"]) <= 100 or float(item["agent_remaining"]) < 0:
        raise ToolError("invalid_input", "SOC 或药剂不能越界")
    item.update({"id": item["uav_id"], "role": item["subgroup"], "battery": item["soc"], "payload": item["agent_remaining"], "schema_version": "uav-v1"})
    return item


def get_fleet_status_v1(fleet: list = None, **_: Any) -> Dict[str, Any]:
    fleet = fleet if fleet is not None else read_json("data/fleet.json")
    records = [normalize_uav_record(row) for row in fleet]
    return {"schema_version": "fleet-v1", "fleet": records, "count": len(records)}


def get_inventory_v1(inventory: Dict[str, Any] = None, **_: Any) -> Dict[str, Any]:
    data = dict(inventory if inventory is not None else read_json("data/inventory.json"))
    for key, value in list(data.items()):
        if isinstance(value, (int, float)) and value < 0:
            raise ToolError("invalid_inventory", "库存不能为负数", {"field": key})
    data.update({"schema_version": "inventory-v1"})
    return data


def calculate_energy_consumption(task_mass: float = 0, capacity_mass: float = 1, mode_rate: float = 0, duration_minutes: float = 0, wind_factor: float = 0, climb_factor: float = 0, aux_rate: float = 0, **kwargs: Any) -> Dict[str, float]:
    rate = kwargs.get("r_mode", mode_rate); duration = kwargs.get("delta_t", duration_minutes)
    positive(task_mass, "task_mass"); positive(capacity_mass, "capacity_mass"); positive(rate, "mode_rate"); positive(duration, "duration_minutes")
    load = min(1.0, task_mass / capacity_mass)
    effective = rate * (1 + 0.45 * load + 0.20 * wind_factor + 0.10 * climb_factor) + aux_rate
    return {"load_ratio": round(load, 4), "effective_rate_percent_per_hour": round(effective, 4), "delta_soc": round(effective * duration / 60, 4)}


def calculate_soc_need(soc_outbound: float = 0, soc_task: float = 0, soc_return: float = 0, soc_reserve: float = 25, **_: Any) -> Dict[str, Any]:
    values = [soc_outbound, soc_task, soc_return, soc_reserve]
    if any(v < 0 for v in values): raise ToolError("invalid_input", "SOC 不能为负数")
    total = sum(values)
    return {"soc_need": round(total, 4), "soc_reserve": soc_reserve, "return_threshold": 25, "feasible_at_full_charge": total <= 100}


def check_uav_feasibility(uav: Dict[str, Any], required_payload: float = 0, soc_need: float = 0, distance_m: float = 0, route_available: bool = True, required_module: str = None, **_: Any) -> Dict[str, Any]:
    d = normalize_uav_record(uav); reasons = []
    if d["status"] in {"fault", "offline"} or d.get("health", 100) < 60: reasons.append("设备不可用")
    if required_payload > d.get("payload_capacity_kg", 0): reasons.append("载荷超限")
    if soc_need > d["soc"] or d["soc"] - soc_need < 25: reasons.append("返航 SOC 低于25%")
    if not route_available: reasons.append("路线不可达")
    if required_module and d.get("payload_module") != required_module: reasons.append("药剂模块不兼容")
    return {"feasible": not reasons, "uav_id": d["uav_id"], "reasons": reasons}


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


def calculate_flp_load(cells: list = None, intensity: float = 1, fuel_factor: float = 1.0, wind_factor: float = 1.0, slope_factor: float = 1.0, **_: Any) -> Dict[str, Any]:
    if cells is None: cells = [{"intensity": intensity, "fuel_factor": fuel_factor, "wind_factor": wind_factor, "slope_factor": slope_factor}]
    loads = [10 * c.get("intensity", 1) * c.get("fuel_factor", 1) * c.get("wind_factor", 1) * c.get("slope_factor", 1) for c in cells]
    return {"fire_load_flp": round(sum(loads), 4), "cell_loads_flp": [round(x, 4) for x in loads], "cell_count": len(loads)}


def calculate_agent_effective_flp(agent_quantity: float, module: str = "water_20l", scene: str = "vegetation", drop_efficiency: float = 0.9, weather_efficiency: float = 1.0, **_: Any) -> Dict[str, Any]:
    kappa = 1.0 if module == "water_20l" and scene != "electrical" else (1.5 if module == "co2_6kg" and scene == "electrical" else (0.25 if module == "co2_6kg" else 0))
    if scene == "electrical" and module != "co2_6kg": kappa = 0
    return {"effective_flp": round(agent_quantity * kappa * drop_efficiency * weather_efficiency, 4), "module": module, "compatible": kappa > 0}


def simulate_fire_round(fire_load_flp: float, growth_flp_per_hour: float = 0, suppression_flp: float = 0, duration_minutes: float = 5, **_: Any) -> Dict[str, Any]:
    positive(fire_load_flp, "fire_load_flp"); positive(growth_flp_per_hour, "growth_flp_per_hour"); positive(duration_minutes, "duration_minutes")
    growth = growth_flp_per_hour * duration_minutes / 60
    after = max(0, fire_load_flp + growth - suppression_flp)
    return {"before_flp": fire_load_flp, "growth_flp": round(growth, 4), "suppression_flp": suppression_flp, "after_flp": round(after, 4), "resource_gap": after > fire_load_flp}


def simulate_supply_cycle(agent_start: float, quantity_used: float = 0, supply_quantity: float = 0, capacity: float = 20, **_: Any) -> Dict[str, Any]:
    end = max(0, min(capacity, agent_start - quantity_used + supply_quantity))
    return {"agent_end": round(end, 4), "used": round(min(agent_start, quantity_used), 4), "supplied": round(end - max(0, agent_start - quantity_used), 4)}


def transition_uav_state(current_state: str, next_state: str, **_: Any) -> Dict[str, Any]:
    allowed = {"available": {"assigned", "charging", "fault"}, "assigned": {"flying", "available", "fault"}, "flying": {"working", "returning", "fault"}, "working": {"returning", "replanning", "fault"}, "returning": {"servicing", "charging", "available", "fault"}, "servicing": {"available", "charging", "fault"}, "charging": {"available", "fault"}, "replanning": {"assigned", "available", "fault"}}
    if next_state != "fault" and next_state not in allowed.get(current_state, set()): raise ToolError("invalid_transition", "非法 UAV 状态转换")
    return {"from": current_state, "to": next_state, "valid": True}


def calculate_resource_gap(required: float, available: float, resource: str = "agent", **_: Any) -> Dict[str, Any]:
    gap = max(0, required - available)
    return {"resource": resource, "required": required, "available": available, "gap": gap, "resource_gap": gap > 0}


def score_dispatch_plan(time_norm: float = 0, residual_norm: float = 0, energy_norm: float = 0, material_norm: float = 0, change_norm: float = 0, **_: Any) -> Dict[str, Any]:
    score = 0.40 * time_norm + 0.30 * residual_norm + 0.15 * energy_norm + 0.10 * material_norm + 0.05 * change_norm
    return {"score": round(score, 6), "lower_is_better": True}


def build_core_tools():
    handlers = {"extract_frames": not_implemented, "detect_fire": demo_observation, "calculate_fire_metrics": calculate_fire_metrics, "analyze_visual_trend": not_implemented, "analyze_with_vlm": not_implemented, "get_water_sources": get_water_sources, "calculate_wind_vector": calculate_wind_vector, "predict_spread": predict_spread, "retrieve_scene_knowledge": not_implemented, "assess_fire_level": assess_fire_level, "estimate_growth": estimate_growth, "match_extinguisher": match_extinguisher, "calculate_resource_need": calculate_resource_need, "validate_plan": validate_plan, "calculate_drone_count": calculate_drone_count, "assign_tasks": assign_tasks, "calculate_distance": calculate_distance, "plan_route": plan_route, "check_battery": check_battery, "check_payload": check_payload, "execute_firefighting": execute_firefighting, "resupply": resupply, "return_to_charge": return_to_charge, "update_fire_state": update_fire_state, "evaluate_result": evaluate_result, "make_next_decision": make_next_decision, "normalize_uav_record": normalize_uav_record, "get_fleet_status_v1": get_fleet_status_v1, "get_inventory_v1": get_inventory_v1, "calculate_energy_consumption": calculate_energy_consumption, "calculate_soc_need": calculate_soc_need, "check_uav_feasibility": check_uav_feasibility, "select_water_source": select_water_source, "calculate_flp_load": calculate_flp_load, "calculate_agent_effective_flp": calculate_agent_effective_flp, "simulate_fire_round": simulate_fire_round, "simulate_supply_cycle": simulate_supply_cycle, "transition_uav_state": transition_uav_state, "calculate_resource_gap": calculate_resource_gap, "score_dispatch_plan": score_dispatch_plan}
    return [FunctionTool(name, handler, "V1 确定性规则 Tool。", "rules" if handler is not not_implemented else "demo-stub") for name, handler in handlers.items()]
