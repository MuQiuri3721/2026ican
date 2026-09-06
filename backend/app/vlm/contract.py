"""vlm-analysis-v1 契约校验与禁项守卫（docs/VLM队员执行手册.md §4.2/§4.3）。

两级处理：
- 身份字段不合法（schema_version 不符 / task_id、round_index 回显不一致）→ 整包不可信，返回 None 由调用方走回退；
- 禁项越界（FLP/风/无人机数量等规则数字、people=absent、水体判定）→ 剥除或钳位 + violations 标注，包仍可用（manual_review 线索）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

SCHEMA_VERSION = "vlm-analysis-v1"

# 手册 §4.3：VLM 绝对不能输出的规则数字/资源/时间字段（小写比对，任意层级剥除）
FORBIDDEN_KEYS = {
    "flp", "fire_load", "fire_load_flp", "fire_cells",
    "fire_area_m2", "affected_area_m2", "burned_area_m2", "area_m2",
    "growth_rate", "spread_rate", "fire_growth",
    "wind_speed", "wind_direction", "beaufort",
    "drone_count", "uav_count", "drone_ids", "hover_altitude",
    "soc", "battery", "battery_percent",
    "water_liters", "w20", "co2", "dosage", "agent_requirement", "extinguisher_amount",
    "control_time", "eta", "completion_time", "extinguish_duration",
    "flight_route", "route_plan", "task_assignment",
}

# people.state：手册 §4.3 判断边界——没有看到人员只能写 not_observed，不能写 absent
PEOPLE_ABSENT_ALIASES = {"absent", "no_people", "none", "not_present", "no_person"}

# 水体：视觉水面只能写 water_candidate，可否取水由 GIS 与规则引擎判断
WATER_FORBIDDEN_STATES = {"confirmed", "usable", "available", "fetchable", "drinkable", "accessible"}
WATER_ALLOWED = "water_candidate"


def _walk_forbidden(node: Any, path: str, violations: List[str]) -> Any:
    """递归剥除禁项键；返回清理后的节点。"""
    if isinstance(node, dict):
        cleaned: Dict[str, Any] = {}
        for key, value in node.items():
            child_path = f"{path}.{key}" if path else str(key)
            if str(key).lower() in FORBIDDEN_KEYS:
                violations.append(f"已剥除禁项字段「{child_path}」（规则数字/资源量不得由 VLM 输出）")
                continue
            cleaned[str(key)] = _walk_forbidden(value, child_path, violations)
        return cleaned
    if isinstance(node, list):
        return [_walk_forbidden(item, path, violations) for item in node]
    return node


def _clamp_people(payload: Dict[str, Any], violations: List[str]) -> None:
    for anchor in ("people", "scene_elements"):
        node = payload.get(anchor)
        if not isinstance(node, dict):
            continue
        people = node.get("people") if anchor == "scene_elements" else node
        if isinstance(people, dict) and str(people.get("state", "")).lower() in PEOPLE_ABSENT_ALIASES:
            people["state"] = "not_observed"
            violations.append(f"people.state=absent 已钳位为 not_observed（{anchor}）")


def _clamp_water(node: Any, violations: List[str]) -> Any:
    if isinstance(node, dict):
        for field in ("state", "status", "usability"):
            if str(node.get(field, "")).lower() in WATER_FORBIDDEN_STATES:
                node[field] = WATER_ALLOWED
                violations.append(f"water.{field} 已钳位为 water_candidate（可否取水由 GIS 与规则引擎判断）")
        for key, value in list(node.items()):
            node[key] = _clamp_water(value, violations)
    elif isinstance(node, list):
        return [_clamp_water(item, violations) for item in node]
    return node


def validate_vlm_analysis(
    payload: Any, task_id: Optional[str] = None, round_index: Optional[int] = None
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """校验并清洗 VLM 输出。返回 (clean|None, report)；report.violations 供前端/审计标注。"""
    report: Dict[str, Any] = {"valid": False, "violations": [], "missing_fields": []}
    if not isinstance(payload, dict):
        report["missing_fields"].append("根节点必须是 JSON object")
        return None, report
    violations: List[str] = []
    schema = payload.get("schema_version")
    if schema != SCHEMA_VERSION:
        report["missing_fields"].append(f"schema_version 必须是 {SCHEMA_VERSION}（实际 {schema!r}）")
        return None, report
    if task_id is not None and payload.get("task_id") not in (None, task_id):
        report["missing_fields"].append(f"task_id 回显不一致（{payload.get('task_id')!r} ≠ {task_id!r}）")
        return None, report
    if round_index is not None:
        echoed = payload.get("round_index")
        try:
            echoed = int(echoed)  # 宽容归一：模型可能回显 "1" 字符串
        except (TypeError, ValueError):
            pass
        if echoed not in (None, round_index):
            report["missing_fields"].append(f"round_index 回显不一致（{payload.get('round_index')!r} ≠ {round_index!r}）")
            return None, report

    cleaned = _walk_forbidden(payload, "", violations)
    _clamp_people(cleaned, violations)
    for anchor in ("water", "scene_elements", "objects"):
        if anchor in cleaned:
            cleaned[anchor] = _clamp_water(cleaned[anchor], violations)

    report["valid"] = True
    report["violations"] = violations
    if violations:
        cleaned["manual_review_required"] = True
    return cleaned, report
