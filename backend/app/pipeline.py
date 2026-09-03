import json
import itertools
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .domain.schemas import InventorySnapshot, UAVRecord


ROOT = Path(__file__).resolve().parents[2]


def read_json(relative_path: str) -> Any:
    with (ROOT / relative_path).open(encoding="utf-8") as file:
        return json.load(file)


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


def normalize(value: float, reference: float) -> float:
    return min(max(value / reference, 0), 1)


def assess_fire(state: Dict[str, Any]) -> Dict[str, Any]:
    config = state["config"]
    fire_area, smoke_area, growth_rate = 1800, 4200, 0.42
    wind_speed = state["scene"]["wind_speed"]
    weights = config["weights"]
    risk_score = (
        weights["fire_area"] * normalize(fire_area, config["reference_fire_area_m2"])
        + weights["smoke_area"] * normalize(smoke_area, config["reference_smoke_area_m2"])
        + weights["wind_speed"] * normalize(wind_speed, config["reference_wind_speed_mps"])
        + weights["growth_rate"] * growth_rate
    )
    level = 1 + sum(risk_score >= threshold for threshold in config["level_thresholds"])
    labels = {1: "I 级 · 低风险", 2: "II 级 · 中等火情", 3: "III 级 · 高风险", 4: "IV 级 · 极高风险"}
    return {"level": level, "label": labels[level], "fire_area_m2": fire_area, "smoke_area_m2": smoke_area, "confidence": 0.91, "risk_score": round(risk_score, 3), "growth_rate": growth_rate, "spread_direction": state["scene"]["wind_direction"]}


def calculate_dispatch(state: Dict[str, Any], fire: Dict[str, Any]) -> Dict[str, Any]:
    config, scene, inventory = state["config"], state["scene"], state["inventory"]
    resource = config["resource"]
    level_factor = resource["level_factors"][fire["level"] - 1]
    required_liters = math.ceil(fire["fire_area_m2"] * resource["base_liters_per_m2"] * level_factor * resource["environment_factor"] * resource["safety_factor"])
    required_drones = max(1, math.ceil(required_liters / 80))
    available = [drone for drone in state["fleet"] if drone["role"] == "firefighting" and drone["battery"] >= config["minimum_battery_percent"]]
    source = scene["water_sources"][0]
    can_control = bool(available) and required_liters <= inventory["water_liters"]
    material_reason = "北侧蓄水池可用且距离较近，建议无人机三执行补水。" if source["available"] and source["distance_m"] <= 1000 else "附近水源不可用，建议切换预装灭火资源。"
    selected = [drone["uav_id"] for drone in available[:required_drones]]
    tasks = ([{"drone_id": uav_id, "task": "主力灭火"} for uav_id in selected]
             if selected else [])
    return {"can_control": can_control, "recommended_material": "water" if source["available"] else "dry_powder", "material_amount": required_liters, "required_drones": required_drones, "selected_uavs": selected, "estimated_minutes": resource["target_minutes"], "tasks": tasks, "reason": material_reason}


def deterministic_v1_dispatch(state: Dict[str, Any], fire: Dict[str, Any], people_status: str = "unknown") -> Dict[str, Any]:
    """按规则生成方案：枚举 E 组合，并始终保留 R 监测及 S 支援分支。"""
    scene, inventory = state["scene"], state["inventory"]
    people_status = people_status if people_status in {"confirmed", "absent", "unknown"} else "unknown"
    fire_type = str(fire.get("fire_type", fire.get("type", "vegetation"))).lower()
    module = "co2_6kg" if fire_type in {"electrical", "oil", "chemical"} else "water_20l"
    quantity = 6.0 if module == "co2_6kg" else 20.0
    fire_load = max(1.0, fire["fire_area_m2"] / 180.0) * (1 + 0.5 * fire.get("growth_rate", 0.42))
    e_candidates = [u for u in state["fleet"] if u.get("uav_id", "").startswith("E") and u.get("status") in {"available", "assigned"} and u.get("health", 0) >= 60 and u.get("soc", 0) >= 25 and (module == "water_20l" or u.get("payload_module") == module)]
    recon = [u for u in state["fleet"] if u.get("uav_id", "").startswith("R") and u.get("status") in {"available", "assigned"} and u.get("health", 0) >= 60 and u.get("soc", 0) >= 25]
    support = [u for u in state["fleet"] if u.get("uav_id", "").startswith("S") and u.get("status") in {"available", "assigned"} and u.get("health", 0) >= 60 and u.get("soc", 0) >= 25]
    origin = scene.get("fire_origin", {"x": 0, "y": 0})
    candidates = []
    for size in range(1, min(4, len(e_candidates)) + 1):
        # combinations, not a prefix: lower-SOC E can be a better feasible alternative
        for selected in itertools.combinations(e_candidates, size):
            total_flp, battery_plan, errors = 0.0, [], []
            for uav in selected:
                pos = uav.get("position", origin); distance = math.hypot(pos.get("x", 0)-origin.get("x", 0), pos.get("y", 0)-origin.get("y", 0))
                outbound = distance / max(uav.get("speed_mps", 8), .1) / 60
                task = 5.0 + (2.0 if people_status == "confirmed" else 0)
                load_ratio = quantity / max(uav.get("payload_capacity_kg", 25), 1)
                rate = uav.get("energy_rate_percent_per_hour", 180) * (1 + .45*load_ratio + .02*scene.get("wind_speed", 0))
                need = rate * (2*outbound + task) / 60
                after = uav.get("soc", 0) - need
                if after < 25: errors.append(f"{uav['uav_id']}:返航SOC低于25%")
                total_flp += quantity * (1.5 if module == "co2_6kg" else 1) * .9
                battery_plan.append({"uav_id":uav["uav_id"],"soc_before":uav.get("soc",0),"soc_need":round(need,2),"soc_after_return":round(after,2),"reserve_percent":25,"outbound_minutes":round(outbound,2),"task_minutes":task})
            available = inventory.get("co2_modules_c6", 0)*6 if module == "co2_6kg" else min(inventory.get("water_liters",0), inventory.get("water_modules_w20",0)*20)
            gaps = []
            if total_flp < fire_load: gaps.append({"resource":"effective_flp","required":round(fire_load,2),"available":round(total_flp,2),"gap":round(fire_load-total_flp,2),"resource_gap":True})
            if available < size*quantity: gaps.append({"resource":module,"required":size*quantity,"available":available,"gap":size*quantity-available,"resource_gap":True})
            candidates.append((not errors and not gaps, selected, battery_plan, total_flp, gaps, errors))
    feasible = [c for c in candidates if c[0]]
    chosen = max(feasible or candidates, key=lambda c: c[3], default=(False, (), [], 0, [], []))
    ok, selected, battery_plan, total_flp, gaps, errors = chosen
    selected_ids = [u["uav_id"] for u in selected]
    r_ids = [recon[0]["uav_id"]] if recon else []
    s_ids = [support[0]["uav_id"]] if support else []
    tasks = [{"drone_id": r_ids[0], "task":"持续侦察", "branch":"reconnaissance"}] if r_ids else []
    tasks += [{"drone_id": u, "task":"主力灭火", "module":module, "target_flp":round(fire_load/max(len(selected),1),2)} for u in selected_ids]
    tasks += [{"drone_id": s_ids[0], "task": "通信广播/疏散引导" if people_status == "confirmed" else ("物流补给" if people_status == "absent" else "复核人员与后备侦察"), "branch":"support"}] if s_ids else []
    alternatives = [{"selected_uavs":[u["uav_id"] for u in c[1]],"feasibility":c[0],"effective_flp":round(c[3],2)} for c in candidates if [u["uav_id"] for u in c[1]] != selected_ids][:8]
    travel = max([p["outbound_minutes"] for p in battery_plan] or [0]); control = 5 + travel*2 + (3 if people_status == "confirmed" else 0)
    return {"schema_version":"uav-dispatch-v1","fleet_shape":{"reconnaissance":2,"suppression":4,"support":2},"can_control":bool(feasible),"feasibility":ok and bool(r_ids) and bool(s_ids),"required_drones":max(1,math.ceil(fire_load/max(quantity*.9,1))),"selected_uavs":r_ids+selected_ids+s_ids,"recommended_material":"co2" if module=="co2_6kg" else "water","material_module":module,"material_amount":len(selected)*quantity,"fire_load_flp":round(fire_load,2),"effective_flp":round(total_flp,2),"resource_gap":gaps+([{"resource":"hard_constraint","gap":";".join(errors),"resource_gap":True}] if errors else []),"battery_plan":battery_plan,"people_branch":people_status,"estimated_control_time":{"earliest_minutes":round(control),"latest_minutes":round(control+max(5,travel+2)),"window_minutes":[round(control),round(control+max(5,travel+2))],"unit":"min"},"estimated_minutes":round(control+max(5,travel+2)),"alternative_plan":alternatives,"tasks":tasks,"reason":"V1硬约束可行" if ok else "V1约束不足，需补给或重规划"}


def run_demo_analysis(scene_id: str, image_name: Optional[str], fire_override: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    state = load_demo_state(scene_id)
    fire = assess_fire(state)
    if fire_override:
        fire.update({key: value for key, value in fire_override.items() if key in {"fire_area_m2", "smoke_area_m2", "growth_rate"}})
    scene = state["scene"]
    dispatch = deterministic_v1_dispatch(state, fire)
    return {"fire_assessment": fire, "environment": {"wind_speed": scene["wind_speed"], "wind_direction": scene["wind_direction"], "altitude": scene["altitude"], "terrain": scene["terrain"], "nearest_water_distance_m": scene["water_sources"][0]["distance_m"]}, "dispatch_plan": dispatch, "source_image": image_name, "data_mode": "固定演示数据 · 规则引擎", "pipeline_stages": [{"id": "ingest", "label": "影像接入", "status": "completed", "source": "上传文件"}, {"id": "vision", "label": "视觉识别", "status": "demo", "source": "YOLO 待接入"}, {"id": "environment", "label": "环境融合", "status": "completed", "source": "固定场景数据"}, {"id": "dispatch", "label": "调度生成", "status": "completed", "source": "规则引擎"}], "fleet": state["fleet"], "inventory": state["inventory"], "explanation": f"当前为{fire['label']}，{scene['wind_direction']}风可能推动火势向{scene['wind_direction']}扩散。{dispatch['reason']}"}


def simulate_monitor(
    analysis: Dict[str, Any],
    elapsed_minutes: float,
    extinguishing_liters: float,
    fleet_snapshot: Optional[list] = None,
    inventory: Optional[Dict[str, Any]] = None,
    image_name: Optional[str] = None,
) -> Dict[str, Any]:
    fire = analysis["fire_assessment"]
    environment = analysis["environment"]
    fleet = normalize_fleet(fleet_snapshot if fleet_snapshot is not None else analysis.get("fleet", []))
    stock = normalize_inventory(inventory if inventory is not None else analysis.get("inventory", {}))
    elapsed = max(0.1, float(elapsed_minutes))
    requested_liters = max(0, float(extinguishing_liters))
    water_liters = max(0, float(stock.get("water_liters", 0)))
    available_drones = sum(1 for drone in fleet if drone.get("subgroup") == "suppression" and drone.get("soc", 0) >= 25 and drone.get("health", 0) >= 60)
    dispatch = analysis.get("dispatch_plan", {})
    interval_count = max(1, math.ceil(elapsed / 5))
    selected_ids = {u for u in dispatch.get("selected_uavs", []) if str(u).startswith("E")}
    material_module = dispatch.get("material_module", "water_20l")
    effective_flp = min(float(dispatch.get("effective_flp", 0)), float(dispatch.get("fire_load_flp", fire["fire_area_m2"])))
    fire_load_before = float(dispatch.get("fire_load_flp", max(1, fire["fire_area_m2"] / 180)))
    fire_load_after = max(0, fire_load_before + fire_load_before * fire.get("growth_rate", 0.42) * elapsed / 60)
    capacity = 20.0 if material_module == "water_20l" else 6.0
    if material_module == "water_20l":
        effective_liters = min(requested_liters, water_liters, stock.get("water_modules_w20", 0) * capacity)
    else:
        effective_liters = min(requested_liters, stock.get("co2_modules_c6", 0) * capacity)
    active = [d for d in fleet if d.get("uav_id") in selected_ids]
    for drone in active:
        rate = drone.get("energy_rate_percent_per_hour", 180)
        pos = drone.get("position", {"x": 0, "y": 0}); origin = analysis.get("fire_origin", {"x": 0, "y": 0})
        distance = math.hypot(pos.get("x", 0)-origin.get("x", 0), pos.get("y", 0)-origin.get("y", 0))
        travel = distance / max(drone.get("speed_mps", 8), .1) / 60
        task_minutes = elapsed
        load_ratio = min(capacity / max(drone.get("payload_capacity_kg", 25), 1), 1)
        adjusted_rate = rate * (1 + .45 * load_ratio + .02 * environment.get("wind_speed", 0))
        soc_need = adjusted_rate * (2 * travel + task_minutes) / 60
        drone["soc"] = max(0, round(drone.get("soc", 0) - soc_need, 2))
        drone["battery"] = drone["soc"]
        share = effective_liters / max(len(active), 1)
        drone["agent_remaining"] = max(0, round(drone.get("agent_remaining", 0) - min(share, capacity), 2))
        drone["payload"] = drone["agent_remaining"]
        drone["status"] = "returning" if drone["soc"] < 25 else "working"
        drone["last_updated"] = datetime.now().isoformat(timespec="seconds")
    if material_module == "co2_6kg":
        stock["co2_modules_c6"] = max(0, stock.get("co2_modules_c6", 0) - math.ceil(effective_liters / capacity) if effective_liters else stock.get("co2_modules_c6", 0))
    else:
        stock["water_liters"] = max(0, water_liters - effective_liters)
        stock["water_modules_w20"] = max(0, stock.get("water_modules_w20", 0) - math.ceil(effective_liters / capacity) if effective_liters else stock.get("water_modules_w20", 0))
    stock["last_updated"] = datetime.now().isoformat(timespec="seconds")
    growth = fire["fire_area_m2"] * fire.get("growth_rate", 0.42) * (1 + 0.04 * environment["wind_speed"]) * elapsed / 60
    reduction = effective_liters * 0.9 * (1 if available_drones else 0.5)
    next_area = max(0, round(fire["fire_area_m2"] + growth - reduction))
    ratio = round((next_area - fire["fire_area_m2"]) / max(fire["fire_area_m2"], 1), 3)
    if next_area <= 300:
        action, reason = "finish", "火焰面积已降至目标阈值，进入效果确认。"
    elif effective_liters <= 0 or requested_liters > water_liters:
        action, reason = "resupply", "当前库存不足以支持本轮灭火，建议先完成补给。"
    elif ratio > 0.08:
        action, reason = "reinforce", "火势仍在扩大，建议请求增援并扩大侦察范围。"
    else:
        action, reason = "continue", "火势受到抑制，继续当前任务并在 5 分钟后复评。"
    return {"next_fire_area_m2": next_area, "next_fire_load_flp": round(fire_load_after, 2), "fire_load_flp": round(fire_load_after, 2), "growth_area_m2": round(growth), "extinguished_area_m2": round(reduction), "change_ratio": ratio, "action": action, "reason": reason, "trigger_reason": reason, "next_check_minutes": 5, "input": {"image_name": image_name if image_name is not None else analysis.get("source_image"), "fleet_snapshot": fleet, "inventory": stock}, "availability": {"firefighting_drones": available_drones, "water_liters": water_liters, "effective_flp": round(effective_flp, 2)}, "resource_consumed": {"water_liters": effective_liters, "module": material_module}, "resource_gap": ([{"resource": "water_liters", "required": requested_liters, "available": water_liters, "gap": requested_liters - water_liters, "resource_gap": True}] if requested_liters > water_liters else []), "battery_plan": [{"uav_id": d["uav_id"], "soc_after": d["soc"]} for d in fleet if d.get("uav_id") in selected_ids], "next_inventory": stock, "next_fleet": fleet}
