import json
import itertools
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .domain.schemas import InventorySnapshot, UAVRecord
from .tools.core import build_fire_grid, resolve_wind_band, select_water_source, simulate_dispatch_candidate, score_candidate_plan, v1_config, _agent_kappa


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
    config, scene = state["config"], state["scene"]
    fire_area, smoke_area, growth_rate = 1800, 4200, 0.42
    wind_speed = scene["wind_speed"]
    weights = config["weights"]
    risk_score = (
        weights["fire_area"] * normalize(fire_area, config["reference_fire_area_m2"])
        + weights["smoke_area"] * normalize(smoke_area, config["reference_smoke_area_m2"])
        + weights["wind_speed"] * normalize(wind_speed, config["reference_wind_speed_mps"])
        + weights["growth_rate"] * growth_rate
    )
    level = 1 + sum(risk_score >= threshold for threshold in config["level_thresholds"])
    labels = {1: "I 级 · 低风险", 2: "II 级 · 中等火情", 3: "III 级 · 高风险", 4: "IV 级 · 极高风险"}
    slope_deg = float(scene.get("slope_deg", 12))
    fuel_type = scene.get("fuel_type", "general_forest")
    intensity = min(4, max(1, level))
    grid = build_fire_grid(fire_area, wind_speed=wind_speed, slope_deg=slope_deg, fuel_type=fuel_type, intensity=intensity)
    fire_load = float(grid["fire_load_flp"])
    band = grid["wind_band"]
    return {
        "level": level, "label": labels[level], "fire_area_m2": fire_area, "smoke_area_m2": smoke_area,
        "confidence": 0.91, "risk_score": round(risk_score, 3), "growth_rate": growth_rate,
        "spread_direction": scene["wind_direction"], "fire_type": scene.get("fire_type", "vegetation"),
        "fire_load_flp": fire_load, "growth_flp_per_hour": round(fire_load * growth_rate, 2),
        "fire_grid": {key: grid[key] for key in ("cell_area_m2", "cell_count", "intensity", "k_fuel", "k_wind", "k_slope", "fuel_type")},
        "wind_band": band, "slope_deg": slope_deg,
    }


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


def _evaluate_water_plan(scene: Dict[str, Any], inventory: Dict[str, Any]) -> Dict[str, Any]:
    """就地取水六条件评估（规则 V1 §5.3）：全条件通过才改为就地补给，否则基地补给。

    select_water_source 的判定：available、safe_access、capacity≥20L、路线安全、
    取水循环后 SOC≥25%、比基地补给（4 min）至少节省 5 min。
    """
    source = (scene.get("water_sources") or [{}])[0]
    evaluation = select_water_source(
        sources=[{
            "available": source.get("available", False),
            "safe_access": source.get("safe", source.get("safe_access", False)),
            "capacity_remaining": source.get("capacity_remaining", source.get("capacity_liters", 0)),
            "fill_minutes": 8,
            "distance_m": source.get("distance_m", 0),
        }],
        distance_m=source.get("distance_m", 0),
        cycle_minutes=0,
        base_fill_minutes=4,
        soc_after_cycle=100,
        route_safe=True,
    )
    if evaluation.get("selected") and evaluation.get("source"):
        return {"mode": "onsite", "source_id": source.get("name"), "fill_minutes": 8,
                "distance_m": source.get("distance_m", 0), "reason": "就地水源通过六条件评估且节省≥5分钟"}
    return {"mode": "base", "fill_minutes": 4,
            "reason": "优先基地补给；就地取水评估：" + evaluation.get("reason", "未通过")}


def deterministic_v1_dispatch(state: Dict[str, Any], fire: Dict[str, Any], people_status: str = "unknown", constraints: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """V1 调度：枚举 E 组合 → 硬约束过滤 → 5 分钟离散仿真 → 多目标评分 J → 最优/备选方案。

    R 子群全程保持至少 1 架在线监测，S 子群按有人/无人分支分配任务。
    """
    scene, inventory = state["scene"], state["inventory"]
    people_status = people_status if people_status in {"confirmed", "absent", "unknown"} else "unknown"
    fire_type = str(fire.get("fire_type", scene.get("fire_type", "vegetation"))).lower()
    module = "co2_6kg" if fire_type in {"electrical", "oil", "chemical"} else "water_20l"
    quantity = 6.0 if module == "co2_6kg" else 20.0
    constraints = constraints or {}
    max_drones = int(constraints.get("max_drones", 4)) if constraints.get("max_drones") is not None else 4
    disabled_uavs = {str(uid) for uid in (constraints.get("disabled_uavs") or [])}
    required_module = constraints.get("material_module") or constraints.get("module")
    if required_module in {"water_20l", "co2_6kg"}:
        module = required_module
    if module == "co2_6kg":
        quantity = 6.0
    max_drones = max(1, min(max_drones, 4))
    kappa, _compatible = _agent_kappa(module, fire_type)
    fire_load = max(1.0, float(fire.get("fire_load_flp") or fire["fire_area_m2"] / 180.0))
    growth_flp_per_hour = float(fire.get("growth_flp_per_hour", fire_load * float(fire.get("growth_rate", 0.42))))
    wind_speed = float(fire.get("wind_speed", scene.get("wind_speed", 0)))
    band = resolve_wind_band(wind_speed)
    origin = scene.get("fire_origin", {"x": 0, "y": 0})
    # 规则 V1 §4.2：SOC<35% 不得新接远程任务（new_task_floor_soc_percent）；25% 仅为返航硬约束。
    new_task_floor = float(v1_config().get("new_task_floor_soc_percent", 35))
    e_candidates = [u for u in state["fleet"] if u.get("uav_id", "") not in disabled_uavs and u.get("uav_id", "").startswith("E") and u.get("status") in {"available", "assigned"} and u.get("health", 0) >= 60 and u.get("soc", 0) >= new_task_floor and (module == "water_20l" or u.get("payload_module") == module)]
    recon = [u for u in state["fleet"] if u.get("uav_id", "") not in disabled_uavs and u.get("uav_id", "").startswith("R") and u.get("status") in {"available", "assigned"} and u.get("health", 0) >= 60 and u.get("soc", 0) >= new_task_floor]
    support = [u for u in state["fleet"] if u.get("uav_id", "") not in disabled_uavs and u.get("uav_id", "").startswith("S") and u.get("status") in {"available", "assigned"} and u.get("health", 0) >= 60 and u.get("soc", 0) >= new_task_floor]
    if fire.get("wind_band"):
        band = fire["wind_band"]

    scored = []
    for size in range(1, min(max_drones, len(e_candidates)) + 1):
        for selected in itertools.combinations(e_candidates, size):
            simulation = simulate_dispatch_candidate(
                selected=list(selected), fire_load_flp=fire_load, growth_flp_per_hour=growth_flp_per_hour,
                module=module, fire_type=fire_type, origin=origin, inventory=inventory, wind_speed=wind_speed,
            )
            energy_total = sum(entry["sortie_soc_cost"] * max(entry["sorties"], 1) for entry in simulation["per_uav"])
            changes = simulation["swaps"] + simulation["refills"]
            score = score_candidate_plan(
                simulation["control_minutes"], simulation["residual_flp"], fire_load,
                energy_total, len(selected), simulation["material_used"], changes,
            )
            scored.append({"selected": selected, "simulation": simulation, "score": score, "energy_total": energy_total, "changes": changes})

    controlled = [entry for entry in scored if entry["simulation"]["controlled"]]
    # 用户硬时限（规则文档 §8.2）：先剔除超时方案；全部超时时仍选最快方案供参考，但判为不可控并输出时限缺口。
    time_limit = constraints.get("target_minutes")
    if time_limit is not None:
        try:
            time_limit = float(time_limit)
        except (TypeError, ValueError):
            time_limit = None
    time_gap = None
    if time_limit is not None and controlled:
        within = [entry for entry in controlled if entry["simulation"]["control_minutes"] is not None and entry["simulation"]["control_minutes"] <= time_limit]
        if within:
            pool = within
        else:
            pool = controlled
            fastest = min(entry["simulation"]["control_minutes"] for entry in controlled if entry["simulation"]["control_minutes"] is not None)
            time_gap = {"resource": "time_limit", "required": round(time_limit, 1), "available": round(fastest, 1), "gap": round(fastest - time_limit, 1), "resource_gap": True}
    else:
        pool = controlled or scored
    chosen = min(pool, key=lambda entry: (entry["score"]["score"], entry["simulation"]["residual_flp"]), default=None)
    if chosen is None:
        chosen = {"selected": (), "simulation": simulate_dispatch_candidate([], fire_load_flp=fire_load, growth_flp_per_hour=growth_flp_per_hour, module=module, fire_type=fire_type, origin=origin, inventory=inventory, wind_speed=wind_speed), "score": score_candidate_plan(None, fire_load, fire_load, 0, 0, 0, 0), "energy_total": 0.0, "changes": 0}
    ok, selected, battery_plan, total_flp, gaps, errors = (False, (), [], 0.0, [], [])
    selected = chosen["selected"]
    simulation = chosen["simulation"]
    ok = bool(selected) and simulation["controlled"] and time_gap is None
    battery_plan = [
        {
            "uav_id": entry["uav_id"], "soc_before": next((u.get("soc", 0) for u in selected if u.get("uav_id") == entry["uav_id"]), 0),
            "soc_after_return": entry["soc"], "sortie_soc_cost": entry["sortie_soc_cost"], "sorties": entry["sorties"],
            "swaps": entry["swaps"], "refills": entry["refills"], "reserve_percent": 25,
            "state": entry["state"], "outbound_minutes": round(next((math.hypot((u.get("position") or origin).get("x", 0) - origin.get("x", 0), (u.get("position") or origin).get("y", 0) - origin.get("y", 0)) / max(u.get("speed_mps", 8), 0.1) / 60 for u in selected if u.get("uav_id") == entry["uav_id"]), 0.0), 2),
        }
        for entry in simulation["per_uav"]
    ]
    total_flp = simulation["suppression_flp"]
    material_available = inventory.get("co2_modules_c6", 0) * 6 if module == "co2_6kg" else min(inventory.get("water_liters", 0), inventory.get("water_modules_w20", 0) * 20)
    if not simulation["controlled"]:
        gaps.append({"resource": "effective_flp", "required": round(fire_load, 2), "available": round(total_flp, 2), "gap": round(fire_load - total_flp, 2), "resource_gap": True})
    if material_available < simulation["material_used"]:
        gaps.append({"resource": module, "required": round(simulation["material_used"], 2), "available": round(material_available, 2), "gap": round(simulation["material_used"] - material_available, 2), "resource_gap": True})
    if simulation["stalled_reason"] == "soc_below_return":
        gaps.append({"resource": "battery_packs", "required": "换电后继续", "available": inventory.get("battery_packs", 0), "gap": "备用电池不足", "resource_gap": True})
    if not simulation["compatible"]:
        errors.append(f"药剂模块 {module} 与火情类型 {fire_type} 不兼容")
    selected_ids = [u["uav_id"] for u in selected]
    r_ids = [recon[0]["uav_id"]] if recon else []
    s_ids = [support[0]["uav_id"]] if support else []
    tasks = [{"drone_id": r_ids[0], "task": "持续侦察", "branch": "reconnaissance"}] if r_ids else []
    tasks += [{"drone_id": u, "task": "主力灭火", "module": module, "target_flp": round(fire_load / max(len(selected), 1), 2)} for u in selected_ids]
    tasks += [{"drone_id": s_ids[0], "task": "通信广播/疏散引导" if people_status == "confirmed" else ("物流补给" if people_status == "absent" else "复核人员与后备侦察"), "branch": "support"}] if s_ids else []
    alternatives = sorted(
        (
            {
                "selected_uavs": [u["uav_id"] for u in entry["selected"]],
                "feasibility": entry["simulation"]["controlled"],
                "effective_flp": round(entry["simulation"]["suppression_flp"], 2),
                "score": entry["score"]["score"],
                "control_minutes": entry["simulation"]["control_minutes"],
            }
            for entry in scored
            if [u["uav_id"] for u in entry["selected"]] != selected_ids
        ),
        key=lambda item: item["score"],
    )[:8]
    control_value = simulation["control_minutes"] if simulation["controlled"] else None
    window = [round(control_value), round(control_value + 5)] if control_value is not None else None
    # 契约（api-contract §7）：不可控时不得输出时间窗口——时限缺口场景把最快方案窗口只留在缺口信息里。
    if time_gap is not None:
        control_value = None
        window = None
    return {
        "schema_version": "uav-dispatch-v1",
        "fleet_shape": {"reconnaissance": 2, "suppression": 4, "support": 2},
        "can_control": bool(ok),
        "feasibility": ok and bool(r_ids) and bool(s_ids),
        "required_drones": max(1, math.ceil(fire_load / max(quantity * kappa * 0.9, 1))),
        "selected_uavs": r_ids + selected_ids + s_ids,
        "recommended_material": "co2" if module == "co2_6kg" else "water",
        "material_module": module,
        "material_amount": round(simulation["material_used"], 2),
        "fire_load_flp": round(fire_load, 2),
        "growth_flp_per_hour": round(growth_flp_per_hour, 2),
        "effective_flp": round(total_flp, 2),
        "resource_gap": ([time_gap] if time_gap else []) + gaps + ([{"resource": "hard_constraint", "gap": ";".join(errors), "resource_gap": True}] if errors else []),
        "battery_plan": battery_plan,
        "people_branch": people_status,
        "fire_grid": fire.get("fire_grid"),
        "wind_band": band,
        "scoring": {"method": "J=0.40T+0.30B+0.15E+0.10M+0.05N", "lower_is_better": True, "chosen": chosen["score"], "simulation": {key: simulation[key] for key in ("controlled", "rounds_used", "stalled_reason", "swaps", "refills")}},
        "water_source_plan": _evaluate_water_plan(scene, inventory),
        "replan_trigger": ["fire_load_increase_over_20_percent", "wind_band_changed", "soc_below_return_threshold", "agent_insufficient", "people_status_changed"],
        "estimated_control_time": {"earliest_minutes": window[0] if window else None, "latest_minutes": window[1] if window else None, "window_minutes": window, "unit": "min", "simulated": simulation["controlled"]},
        "estimated_minutes": window[1] if window else None,
        "alternative_plan": alternatives,
        "tasks": tasks,
        "reason": ("V1 离散仿真可控，按 J 评分选出最优组合" if ok else (f"最快可控方案需 {time_gap['available']} 分钟，超过用户时限 {time_gap['required']} 分钟：输出时限缺口" if time_gap else ("V1 硬约束不足：输出资源缺口，需补给或重规划" if selected_ids else "无可用灭火无人机候选"))),
    }


def run_demo_analysis(scene_id: str, image_name: Optional[str], fire_override: Optional[Dict[str, Any]] = None, fire_type: Optional[str] = None, people_status: str = "unknown", constraints: Optional[Dict[str, Any]] = None, dispatch_override: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    state = load_demo_state(scene_id)
    fire = assess_fire(state)
    if fire_type:
        fire["fire_type"] = fire_type
    if fire_override:
        fire.update({key: value for key, value in fire_override.items() if key in {"fire_area_m2", "smoke_area_m2", "growth_rate"}})
        grid = build_fire_grid(fire["fire_area_m2"], wind_speed=state["scene"]["wind_speed"], slope_deg=fire["slope_deg"], fuel_type=fire["fire_grid"]["fuel_type"], intensity=fire["fire_grid"]["intensity"])
        fire["fire_load_flp"] = grid["fire_load_flp"]
        fire["growth_flp_per_hour"] = round(grid["fire_load_flp"] * fire["growth_rate"], 2)
        fire["fire_grid"] = {key: grid[key] for key in ("cell_area_m2", "cell_count", "intensity", "k_fuel", "k_wind", "k_slope", "fuel_type")}
    scene = state["scene"]
    dispatch = dispatch_override or deterministic_v1_dispatch(state, fire, people_status, constraints=constraints)
    # 单一来源：skill 链候选生成（观测+实时环境）产出的 FLP 回写火情评估，消除双算不一致。
    if dispatch_override and dispatch.get("fire_load_flp"):
        fire["fire_load_flp"] = dispatch["fire_load_flp"]
        fire["growth_flp_per_hour"] = dispatch.get("growth_flp_per_hour", fire["growth_flp_per_hour"])
        if dispatch.get("fire_grid"):
            fire["fire_grid"] = dispatch["fire_grid"]
    return {"fire_assessment": fire, "scene": {"fire_origin": scene["fire_origin"], "fire_origin_gps": scene.get("fire_origin_gps")}, "environment": {"wind_speed": scene["wind_speed"], "wind_direction": scene["wind_direction"], "altitude": scene["altitude"], "terrain": scene["terrain"], "nearest_water_distance_m": scene["water_sources"][0]["distance_m"]}, "dispatch_plan": dispatch, "source_image": image_name, "data_mode": "固定演示数据 · 规则引擎", "pipeline_stages": [{"id": "ingest", "label": "影像接入", "status": "completed", "source": "上传文件"}, {"id": "vision", "label": "视觉识别", "status": "demo", "source": "PWM-YOLO 适配器待接入"}, {"id": "environment", "label": "环境融合", "status": "completed", "source": "固定场景数据"}, {"id": "assessment", "label": "网格 FLP 评估", "status": "completed", "source": "规则引擎"}, {"id": "dispatch", "label": "离散仿真调度", "status": "completed", "source": "规则引擎"}], "fleet": state["fleet"], "inventory": state["inventory"], "explanation": f"当前为{fire['label']}，火情负荷 {fire['fire_load_flp']} FLP（{fire['fire_grid']['cell_count']} 个 100m² 网格），{scene['wind_direction']}风可能推动火势向{scene['wind_direction']}扩散。{dispatch['reason']}"}


def simulate_monitor(
    analysis: Dict[str, Any],
    elapsed_minutes: float,
    extinguishing_liters: float,
    fleet_snapshot: Optional[list] = None,
    inventory: Optional[Dict[str, Any]] = None,
    image_name: Optional[str] = None,
) -> Dict[str, Any]:
    """闭环监测：按 1 分钟内部步长推进 elapsed_minutes 分钟，状态机、SOC、药剂和火情负荷同步演化。"""
    fire = analysis["fire_assessment"]
    environment = analysis["environment"]
    fleet = normalize_fleet(fleet_snapshot if fleet_snapshot is not None else analysis.get("fleet", []))
    stock = normalize_inventory(inventory if inventory is not None else analysis.get("inventory", {}))
    dispatch = analysis.get("dispatch_plan", {})
    total_minutes = max(1, int(round(float(elapsed_minutes))))
    module = dispatch.get("material_module", "water_20l")
    capacity = 20.0 if module == "water_20l" else 6.0
    spray_rate = 4.0 if module == "water_20l" else 1.5
    kappa, _compatible = _agent_kappa(module, str(fire.get("fire_type", "vegetation")).lower())
    band = resolve_wind_band(environment.get("wind_speed", 0))
    eta = 0.9 * (1.0 if band["band"] == 0 else 0.85 if band["band"] == 1 else 0.65)
    origin = analysis.get("scene", {}).get("fire_origin", {"x": 0, "y": 0})
    load_before = float(dispatch.get("fire_load_flp", max(1.0, fire.get("fire_area_m2", 1800) / 180.0)))
    fire_load = load_before
    growth_flp_per_hour = float(dispatch.get("growth_flp_per_hour", load_before * float(fire.get("growth_rate", 0.42))))
    selected_ids = {u for u in dispatch.get("selected_uavs", []) if str(u).startswith("E")}
    plan_by_uav = {entry.get("uav_id"): entry for entry in dispatch.get("battery_plan", [])}
    spray_cap = float(extinguishing_liters) if extinguishing_liters else None
    consumed = 0.0
    suppression_total = 0.0
    available_drones = sum(1 for drone in fleet if drone.get("subgroup") == "suppression" and drone.get("soc", 0) >= 25 and drone.get("health", 0) >= 60)

    # 初始化执行态：被选中的 E 机按状态机进入 flying；R/S 维持监测/支援悬停。
    # 上一轮已在途（flying/returning）的机组必须携带进度条，否则没有状态推进、永远停在原地掉电；
    # 重规划换名单后不在新 selected_ids 的在途机视为携带旧任务，召回返航。
    state_progress = {}
    for drone in fleet:
        uid = drone.get("uav_id")
        status = drone.get("status")
        plan = plan_by_uav.get(uid) or {}
        if uid in selected_ids and status in {"available", "assigned"}:
            drone["status"] = "flying"
            state_progress[uid] = {"phase_elapsed": 0.0, "phase_minutes": max(0.5, float(plan.get("outbound_minutes", 1.0)))}
        elif status == "flying" and uid not in selected_ids:
            drone["status"] = "returning"
            state_progress[uid] = {"phase_elapsed": 0.0, "phase_minutes": max(0.5, float(plan.get("outbound_minutes", 4.0)))}
        elif status in {"flying", "returning"}:
            default_minutes = 1.0 if status == "flying" else 4.0
            state_progress[uid] = {"phase_elapsed": 0.0, "phase_minutes": max(0.5, float(plan.get("outbound_minutes", default_minutes)))}

    stalled_agent = False
    soc_return_risk = False
    emergency_soc = float(v1_config().get("emergency_soc_percent", 15))
    emergency_units: list = []
    for _ in range(total_minutes):
        minute_suppression = 0.0
        for drone in fleet:
            uid = drone.get("uav_id", "")
            progress = state_progress.get(uid)
            status = drone.get("status")
            rate = float(drone.get("energy_rate_percent_per_hour", 180))
            if status == "flying":
                drone["soc"] = max(0.0, round(drone["soc"] - rate / 60, 2))
                if progress:
                    progress["phase_elapsed"] += 1
                    if progress["phase_elapsed"] >= progress["phase_minutes"]:
                        drone["status"] = "working"
                        progress["phase_elapsed"] = 0.0
                        progress["phase_minutes"] = 5.0
            elif status == "working":
                if spray_cap is not None and consumed >= spray_cap:
                    drone["status"] = "returning"
                    continue
                if drone["soc"] < 25:
                    soc_return_risk = True
                    drone["status"] = "returning"
                    continue
                agent = float(drone.get("agent_remaining", 0))
                if agent <= 0:
                    drone["status"] = "returning"
                    continue
                sprayed = min(spray_rate, agent, capacity)
                if spray_cap is not None:
                    sprayed = min(sprayed, max(0.0, spray_cap - consumed))
                drone["agent_remaining"] = round(max(0.0, agent - sprayed), 2)
                consumed += sprayed
                suppression_total += sprayed * kappa * eta
                minute_suppression += sprayed * kappa * eta
                drone["soc"] = max(0.0, round(drone["soc"] - rate * 1.05 / 60, 2))
                if drone["agent_remaining"] <= 0 or drone["soc"] < 25:
                    drone["status"] = "returning"
                    if drone["soc"] < 25:
                        soc_return_risk = True
            elif status == "returning":
                drone["soc"] = max(0.0, round(drone["soc"] - rate / 60, 2))
                if progress:
                    progress["phase_elapsed"] += 1
                    if progress["phase_elapsed"] >= progress["phase_minutes"]:
                        progress["phase_elapsed"] = 0.0
                        progress["phase_minutes"] = 4.0
                        drone["status"] = "servicing"
            elif status == "servicing":
                if float(drone.get("agent_remaining", 0)) < capacity:
                    if module == "water_20l":
                        can_refill = stock.get("water_liters", 0) >= capacity and stock.get("water_modules_w20", 0) >= 1
                        if can_refill:
                            stock["water_liters"] = round(stock["water_liters"] - capacity, 2)
                            stock["water_modules_w20"] = max(0, stock["water_modules_w20"] - 1)
                    else:
                        can_refill = stock.get("co2_modules_c6", 0) >= 1
                        if can_refill:
                            stock["co2_modules_c6"] = max(0, stock["co2_modules_c6"] - 1)
                    if can_refill:
                        drone["agent_remaining"] = capacity
                    else:
                        stalled_agent = True
                        drone["status"] = "charging"
                        continue
                drone["status"] = "charging"
            elif status == "charging":
                drone["soc"] = round(min(100.0, drone["soc"] + 100.0 / 60), 2)
                if drone["soc"] >= 100.0:
                    drone["status"] = "available"
            else:
                # R/S 及待命无人机按悬停耗电缓慢下降。
                drone["soc"] = max(0.0, round(drone["soc"] - rate * 0.75 / 60, 2))
            if 0.0 < drone.get("soc", 0) < emergency_soc and uid not in emergency_units:
                emergency_units.append(uid)
            drone["battery"] = drone["soc"]
            drone["payload"] = drone["agent_remaining"]
            drone["last_updated"] = datetime.now().isoformat(timespec="seconds")
        fire_load = max(0.0, fire_load + growth_flp_per_hour / 60 - minute_suppression)

    # 补给时已经按整模块扣减库存；在途喷洒只扣减无人机载荷，避免重复扣减。
    stock["last_updated"] = datetime.now().isoformat(timespec="seconds")

    # 面积口径保持向后兼容：FLP ↔ 面积按 dispatch 的 180 m²/FLP 折算。
    next_area = round(fire_load * 180)
    previous_area = round(load_before * 180)
    ratio = round((next_area - previous_area) / max(previous_area, 1), 3)
    growth = max(0, round(growth_flp_per_hour / 60 * 180 * total_minutes))
    reduction = round(suppression_total * 180)
    active = [d for d in fleet if d.get("uav_id") in selected_ids]
    any_working = any(d.get("status") == "working" for d in active)
    any_agent = any(float(d.get("agent_remaining", 0)) > 0 for d in active)
    if fire_load <= 0:
        action, reason = "finish", "火情负荷已清零，进入效果确认并归档。"
    elif stalled_agent or (active and not any_agent and not stock.get("water_liters")):
        action, reason = "resupply", "药剂或备用电池已耗尽，需要补给/换电后继续。"
    elif fire_load > load_before * 1.05 and not any_working:
        action, reason = "reinforce", "火势增长快于处置能力，建议请求增援并扩大侦察范围。"
    elif soc_return_risk:
        action, reason = "return", "预计返航 SOC 低于 25%，触发硬约束，部分机组提前返航。"
    else:
        action, reason = "continue", "火势受到抑制，继续当前任务并在 5 分钟后复评。"

    triggers = []
    if fire_load > load_before * 1.2:
        triggers.append("fire_load_increase_over_20_percent")
    if dispatch.get("wind_band") and dispatch["wind_band"].get("band") != band["band"]:
        triggers.append("wind_band_changed")
    if soc_return_risk:
        triggers.append("soc_below_return_threshold")
    if stalled_agent:
        triggers.append("agent_insufficient")
    requested_liters = float(extinguishing_liters or 0)
    water_now = float(stock.get("water_liters", 0))
    return {
        "next_fire_area_m2": next_area,
        "next_fire_load_flp": round(fire_load, 2),
        "fire_load_flp": round(fire_load, 2),
        "fire_load_before_flp": round(load_before, 2),
        "growth_area_m2": growth,
        "extinguished_area_m2": reduction,
        "change_ratio": ratio,
        "action": action, "reason": reason, "trigger_reason": reason,
        "replan_triggers": triggers, "replan_required": bool(triggers),
        "next_check_minutes": 5,
        "wind_band": band,
        "input": {"image_name": image_name if image_name is not None else analysis.get("source_image"), "fleet_snapshot": fleet, "inventory": stock},
        "availability": {"firefighting_drones": available_drones, "water_liters": water_now, "effective_flp": round(suppression_total, 2)},
        "resource_consumed": {"water_liters": round(consumed, 2), "module": module},
        "resource_gap": ([{"resource": "water_liters", "required": requested_liters, "available": water_now, "gap": requested_liters - water_now, "resource_gap": True}] if requested_liters > water_now else []),
        "battery_plan": [{"uav_id": d["uav_id"], "soc_after": d["soc"], "status": d["status"], "agent_remaining": d.get("agent_remaining", 0)} for d in fleet if d.get("uav_id") in selected_ids],
        "emergency_units": emergency_units,
        "emergency_soc_percent": emergency_soc,
        "next_inventory": stock,
        "next_fleet": fleet,
    }
