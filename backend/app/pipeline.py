import json
import math
from pathlib import Path
from typing import Any, Dict, Optional


ROOT = Path(__file__).resolve().parents[2]


def read_json(relative_path: str) -> Any:
    with (ROOT / relative_path).open(encoding="utf-8") as file:
        return json.load(file)


def load_demo_state(scene_id: str) -> Dict[str, Any]:
    scene = read_json("data/scene.json")
    if scene["scene_id"] != scene_id:
        raise ValueError(f"未知演示场景: {scene_id}")
    return {"scene": scene, "fleet": read_json("data/fleet.json"), "inventory": read_json("data/inventory.json"), "config": read_json("configs/simulation.json")}


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
    return {"can_control": can_control, "recommended_material": "water" if source["available"] else "dry_powder", "material_amount": required_liters, "required_drones": required_drones, "estimated_minutes": resource["target_minutes"], "tasks": [{"drone_id": "DR-01", "task": "持续侦察"}, {"drone_id": "DR-02", "task": "主力灭火"}, {"drone_id": "DR-03", "task": "水源补给"}], "reason": material_reason}


def run_demo_analysis(scene_id: str, image_name: Optional[str], fire_override: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    state = load_demo_state(scene_id)
    fire = assess_fire(state)
    if fire_override:
        fire.update({key: value for key, value in fire_override.items() if key in {"fire_area_m2", "smoke_area_m2", "growth_rate"}})
    scene = state["scene"]
    dispatch = calculate_dispatch(state, fire)
    return {"fire_assessment": fire, "environment": {"wind_speed": scene["wind_speed"], "wind_direction": scene["wind_direction"], "altitude": scene["altitude"], "terrain": scene["terrain"], "nearest_water_distance_m": scene["water_sources"][0]["distance_m"]}, "dispatch_plan": dispatch, "source_image": image_name, "data_mode": "固定演示数据 · 规则引擎", "pipeline_stages": [{"id": "ingest", "label": "影像接入", "status": "completed", "source": "上传文件"}, {"id": "vision", "label": "视觉识别", "status": "demo", "source": "YOLO 待接入"}, {"id": "environment", "label": "环境融合", "status": "completed", "source": "固定场景数据"}, {"id": "dispatch", "label": "调度生成", "status": "completed", "source": "规则引擎"}], "fleet": state["fleet"], "inventory": state["inventory"], "explanation": f"当前为{fire['label']}，{scene['wind_direction']}风可能推动火势向{scene['wind_direction']}扩散。{dispatch['reason']}"}


def simulate_monitor(analysis: Dict[str, Any], elapsed_minutes: float, extinguishing_liters: float) -> Dict[str, Any]:
    fire = analysis["fire_assessment"]
    environment = analysis["environment"]
    elapsed = max(0.1, elapsed_minutes)
    growth = fire["fire_area_m2"] * fire.get("growth_rate", 0.42) * (1 + 0.04 * environment["wind_speed"]) * elapsed / 60
    reduction = extinguishing_liters * 0.9
    next_area = max(0, round(fire["fire_area_m2"] + growth - reduction))
    ratio = round((next_area - fire["fire_area_m2"]) / max(fire["fire_area_m2"], 1), 3)
    if next_area <= 300:
        action, reason = "finish", "火焰面积已降至目标阈值，进入效果确认。"
    elif ratio > 0.08:
        action, reason = "reinforce", "火势仍在扩大，建议请求增援并扩大侦察范围。"
    elif extinguishing_liters <= 0:
        action, reason = "resupply", "本轮没有有效灭火资源消耗，建议先完成补给。"
    else:
        action, reason = "continue", "火势受到抑制，继续当前任务并在 5 分钟后复评。"
    return {"next_fire_area_m2": next_area, "growth_area_m2": round(growth), "extinguished_area_m2": round(reduction), "change_ratio": ratio, "action": action, "reason": reason, "next_check_minutes": 5}
