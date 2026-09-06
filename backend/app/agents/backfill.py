"""单机失能补位决策（FE-34，设计移植自 firepatrol-agents backfill.py）。

分界口径：补位 = 方案内换机（同药剂、同规模、同目标，**不经审批门**，立即生效）；
重规划 = 方案前提被打破后的重新组织（仍走审批）。
候选两档由规则引擎算好（ready_now = 立即出动；ready_after = 换电/补给一轮后出动），
大脑只做选择与给理由；GLM 不可用/超时/输出非法 → 确定性降级：ready_now 取 SOC 最高。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from ..agentkit.brain import AgentBrain
from ..agentkit.llm import extract_json
from .blackboard import post_message

BACKFILL_PROMPT = (
    "你是灭火调度的战术大脑：一架执行中的灭火机机电失能，立刻决定派谁顶替。"
    "候选分两类（门槛已由规则算好）：ready_now = SOC 够「一趟架次+返航储备」可立即出动；"
    "ready_after = 换电/补给一轮后可出动。"
    "选择依据（按序）：压制不中断（ready_now 优先）> SOC 余量。"
    "两类都空选 none——宁缺毋滥，交给每轮自主研判去重规划。"
    "只输出 JSON：{\"choice\": \"机号或none\", \"rationale\": \"60字内理由\"}"
)

_BRAIN = AgentBrain(BACKFILL_PROMPT)


def decide(candidates: Dict[str, List[Dict[str, Any]]], context: Dict[str, Any]) -> Dict[str, Any]:
    """补位决策入口：GLM 优先，确定性规则兜底，永不抛异常。"""
    fallback = rule_fallback(candidates)
    if fallback["choice"] == "none":
        return fallback  # 无候选时不必问大脑
    brief = json.dumps({"faulted": context.get("faulted"), "candidates": candidates,
                        "fire_load_flp": context.get("fire_load_flp")}, ensure_ascii=False)
    text, _trace = _BRAIN.run(f"灭火机 {'/'.join(context.get('faulted', []))} 失能，决定补位机。",
                              brief, max_tokens=120)
    parsed = extract_json(text or "")
    if parsed:
        choice = str(parsed.get("choice", "")).strip()
        valid = {c["uav_id"] for group in candidates.values() for c in group}
        if choice in valid:
            return {"choice": choice, "rationale": str(parsed.get("rationale", ""))[:120], "source": "glm"}
    return fallback


def rule_fallback(candidates: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """确定性降级：ready_now 取 SOC 最高；其次 ready_after；皆空 → none。"""
    ready = candidates.get("ready_now") or []
    after = candidates.get("ready_after") or []
    if ready:
        best = max(ready, key=lambda c: c["soc"])
        return {"choice": best["uav_id"], "rationale": f"确定性降级：立即可用候选中 {best['uav_id']} SOC 最高（{best['soc']:.0f}%），压制不中断",
                "source": "rule-fallback"}
    if after:
        best = max(after, key=lambda c: c["soc"])
        return {"choice": best["uav_id"], "rationale": f"确定性降级：无立即可用候选，{best['uav_id']}（SOC {best['soc']:.0f}%）换电/补给一轮后顶替",
                "source": "rule-fallback"}
    return {"choice": "none", "rationale": "无满足出动门槛的备用机，交由自主研判决定重规划或降级", "source": "rule-fallback"}


def build_candidates(fleet: List[Dict[str, Any]], selected_ids: set, capacity: float,
                     outbound_cost_soc: float = 25.0) -> Dict[str, List[Dict[str, Any]]]:
    """规则引擎口径的两档补位候选（不选中、非故障、健康达标的 E 机）。

    ready_now：SOC 足够「出动+返航储备」；ready_after：SOC 够安全但需先换电（库存有包）。
    """
    packs = True  # 换电可行性由执行层在换电时刻按库存判定，这里只按 SOC 分档
    ready_now: List[Dict[str, Any]] = []
    ready_after: List[Dict[str, Any]] = []
    for drone in fleet:
        uid = drone.get("uav_id", "")
        if uid in selected_ids or drone.get("subgroup") != "suppression":
            continue
        if drone.get("status") in {"fault"} or drone.get("health", 100) < 60:
            continue
        soc = float(drone.get("soc", 0))
        entry = {"uav_id": uid, "soc": round(soc, 1), "status": drone.get("status")}
        if soc - outbound_cost_soc >= 25:
            ready_now.append(entry)
        elif soc >= 35 and packs:
            ready_after.append(entry)
    ready_now.sort(key=lambda c: -c["soc"])
    ready_after.sort(key=lambda c: -c["soc"])
    return {"ready_now": ready_now, "ready_after": ready_after}


def announce(analysis_id: str, faulted: str, decision: Dict[str, Any],
             candidates: Dict[str, List[Dict[str, Any]]], round_number: int) -> None:
    """失能与补位消息（黑板协议，前端协作流直接渲染）。round 用于幂等去重。"""
    post_message(analysis_id, "UAV_FAULT", "simulator", "commander",
                 f"⚠ {faulted} 遥测中断、电量骤降，按机电故障处置，立即评估补位。",
                 {"faulted": faulted, "round": round_number}, source="rules")
    choice = decision["choice"]
    if choice != "none":
        post_message(analysis_id, "BACKFILL", "suppression", "commander",
                     f"🔁 补位决策（{decision['source']}）：{faulted} 失能 → {choice} 顶替"
                     f"（方案内换机，不改目标与规模，无需重新审批）。{decision['rationale']}",
                     {"faulted": faulted, "choice": choice, "candidates": candidates},
                     source=decision["source"])
    else:
        post_message(analysis_id, "BACKFILL", "suppression", "commander",
                     f"🔁 补位决策（{decision['source']}）：{faulted} 失能，无满足出动门槛的备用机；"
                     f"{decision['rationale']}。移交自主研判。",
                     {"faulted": faulted, "choice": "none"}, source=decision["source"])
