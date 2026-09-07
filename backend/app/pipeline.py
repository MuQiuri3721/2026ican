import json
import itertools
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .domain.schemas import InventorySnapshot, UAVRecord
# rules 层迁移（AG-4）：冻结数值实现已迁至 rules/engine.py，此处 re-export 兼容
from .rules.engine import (
    assess_fire, build_fire_grid, deterministic_v1_dispatch, load_demo_state,
    normalize_fleet, normalize_inventory, resolve_wind_band, select_water_source,
    simulate_monitor, v1_config, ZIXIAHU_BASE_GPS,
)

from .agents.graph import MissionGraph
from .agents.recon import RECON
from .agents.suppression import SUPPRESSION
from .agents.support import SUPPORT
# 原生轻量任务图（AG-5）：recon 研判 / suppression 调度 / support 分支
_MISSION_GRAPH = MissionGraph(RECON, SUPPRESSION, SUPPORT)



ROOT = Path(__file__).resolve().parents[2]


def read_json(relative_path: str) -> Any:
    with (ROOT / relative_path).open(encoding="utf-8") as file:
        return json.load(file)








# 紫霞湖水库（OSM 实测）：演训模拟场景的机群基地锚点（FE-18）
ZIXIAHU_BASE_GPS = (32.062229, 118.839016)






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






def run_demo_analysis(scene_id: str, image_name: Optional[str], fire_override: Optional[Dict[str, Any]] = None, fire_type: Optional[str] = None, people_status: str = "unknown", constraints: Optional[Dict[str, Any]] = None, dispatch_override: Optional[Dict[str, Any]] = None, scenario: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    state = load_demo_state(scene_id)
    if scenario and scenario.get("fire_origin"):
        # 演训模拟（FE-18）：随机火点覆盖相对框架原点，并按紫霞湖基地反演真实 GPS 锚点，
        # 保证机群停靠位在真实世界恒为紫霞湖，而框架内距离（出动时间）随火点位置变化。
        state["scene"]["fire_origin"] = {"x": scenario["fire_origin"]["x"], "y": scenario["fire_origin"]["y"]}
        positions = [uav.get("position") or {"x": 0, "y": 0} for uav in state["fleet"]]
        avg_x = sum(p["x"] for p in positions) / max(len(positions), 1)
        avg_y = sum(p["y"] for p in positions) / max(len(positions), 1)
        lat = ZIXIAHU_BASE_GPS[0] + (scenario["fire_origin"]["y"] - avg_y) / 111320
        # 余弦参考统一用基地纬度（与 scenarios.random_scenario 同源），避免末位舍入抖动
        lng = ZIXIAHU_BASE_GPS[1] + (scenario["fire_origin"]["x"] - avg_x) / (111320 * math.cos(math.radians(ZIXIAHU_BASE_GPS[0])))
        state["scene"]["fire_origin_gps"] = {"latitude": round(lat, 6), "longitude": round(lng, 6)}
        scenario["fire_origin_gps"] = state["scene"]["fire_origin_gps"]
    fire = RECON.assess(state, fire_override)
    if fire_type:
        fire["fire_type"] = fire_type
    scene = state["scene"]
    dispatch = dispatch_override or SUPPRESSION.dispatch(state, fire, people_status, constraints)
    # 单一来源：skill 链候选生成（观测+实时环境）产出的 FLP 回写火情评估，消除双算不一致。
    if dispatch_override and dispatch.get("fire_load_flp"):
        fire["fire_load_flp"] = dispatch["fire_load_flp"]
        fire["growth_flp_per_hour"] = dispatch.get("growth_flp_per_hour", fire["growth_flp_per_hour"])
        if dispatch.get("fire_grid"):
            fire["fire_grid"] = dispatch["fire_grid"]
    return {"fire_assessment": fire, "scene": {"fire_origin": scene["fire_origin"], "fire_origin_gps": scene.get("fire_origin_gps")}, "environment": {"wind_speed": scene["wind_speed"], "wind_direction": scene["wind_direction"], "altitude": scene["altitude"], "terrain": scene["terrain"], "nearest_water_distance_m": scene["water_sources"][0]["distance_m"]}, "dispatch_plan": dispatch, "source_image": image_name, "data_mode": "固定演示数据 · 规则引擎", "pipeline_stages": [{"id": "ingest", "label": "影像接入", "status": "completed", "source": "上传文件"}, {"id": "vision", "label": "视觉识别", "status": "demo", "source": "PWM-YOLO 适配器待接入"}, {"id": "environment", "label": "环境融合", "status": "completed", "source": "固定场景数据"}, {"id": "assessment", "label": "网格 FLP 评估", "status": "completed", "source": "规则引擎"}, {"id": "dispatch", "label": "离散仿真调度", "status": "completed", "source": "规则引擎"}], "fleet": state["fleet"], "inventory": state["inventory"], "explanation": f"当前为{fire['label']}，火情负荷 {fire['fire_load_flp']} FLP（{fire['fire_grid']['cell_count']} 个 100m² 网格），{scene['wind_direction']}风可能推动火势向{scene['wind_direction']}扩散。{dispatch['reason']}"}


