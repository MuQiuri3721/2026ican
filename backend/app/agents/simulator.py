"""⑤ 仿真评估/裁判 Agent：每轮自主研判（LLM 优先，conservative 降级，来源显式标注）。

降级行为约定：LLM 离线/失败时 conservative 研判恒输出 continue——离线演示的调度行为
与既有确定性触发器完全一致；只有 GLM 在线时才可能在无确定性触发器的情况下建议 replan
（以 llm_judgment_replan 触发器来源并入既有重规划通道，仍需再过审批门）。
"""
from typing import Any, Dict

from ..agentkit import llm
from ..agentkit.base import BaseAgent
from ..agentkit.llm import extract_json
from ..agentkit.prompts import SIMULATOR_PROMPT
from .blackboard import post_message


class SimulatorAgent(BaseAgent):
    agent_id = "simulator"
    name = "仿真评估"
    role = "system"
    subgroup = "system"
    prompt = SIMULATOR_PROMPT
    tools: Dict[str, Any] = {}

    def execute_round(self, analysis: Dict[str, Any], elapsed_minutes: int,
                      extinguishing_liters: float = 40, fleet_snapshot=None, inventory_snapshot=None) -> Dict[str, Any]:
        """轮次执行：调用 rules.simulate_monitor（1 分钟步长状态机，冻结）。"""
        from ..rules.engine import simulate_monitor

        return simulate_monitor(analysis, elapsed_minutes,
                                extinguishing_liters=extinguishing_liters,
                                fleet_snapshot=fleet_snapshot, inventory_snapshot=inventory_snapshot)

    def judge(self, analysis_id: str, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        """每轮自主研判：返回并落库结构化研判 {situation, severity, decision, reason, source}。"""
        brief = {
            "round": snapshot.get("round"),
            "flp_before": snapshot.get("flp_before"),
            "flp_after": snapshot.get("flp_after"),
            "action": snapshot.get("action"),
            "triggers": snapshot.get("triggers", []),
            "min_soc": snapshot.get("min_soc", 100),
            "water_liters": snapshot.get("water_liters"),
            "wind_speed": snapshot.get("wind_speed"),
            "people": snapshot.get("people"),
        }
        judgment, source = self._judge_llm(brief)
        if judgment is None:
            judgment, source = _conservative_judgment(brief), "conservative-fallback"
        post_message(analysis_id, "JUDGMENT", self.agent_id, "commander",
                     judgment.get("situation", "态势保持"),
                     {**judgment, "source": source}, source=source)
        return {**judgment, "source": source}

    def _judge_llm(self, brief: Dict[str, Any]) -> tuple[Dict[str, Any] | None, str]:
        import json as _json
        text, _ = self.think("对当前轮次做自主研判，按要求输出 JSON。", _json.dumps(brief, ensure_ascii=False), max_tokens=700)
        parsed = llm.extract_json(text or "")
        if not parsed:
            return None, "parse-failed"
        decision = parsed.get("decision")
        if decision not in ("continue", "replan", "terminate"):
            return None, "invalid-decision"
        severity = parsed.get("severity")
        if severity not in ("low", "medium", "high", "critical"):
            parsed["severity"] = "medium"
        parsed.setdefault("situation", "态势研判")
        parsed.setdefault("reason", "")
        return parsed, "glm"


def _conservative_judgment(brief: Dict[str, Any]) -> Dict[str, Any]:
    """确定性降级研判：只陈述征象，决策恒为 continue（离线行为与既有规则完全一致）。"""
    rising = (brief.get("flp_after") or 0) > (brief.get("flp_before") or 0)
    min_soc = brief.get("min_soc", 100)
    signs = []
    if rising:
        signs.append("火情负荷回升")
    if (min_soc or 100) < 25:
        signs.append("存在低于返航阈值的单元")
    situation = "、".join(signs) if signs else "火情按预期演化，机群状态正常"
    return {
        "situation": f"第 {brief.get('round')} 轮：{situation}。",
        "severity": "high" if rising and brief.get("triggers") else ("medium" if rising else "low"),
        "decision": "continue",
        "reason": "确定性降级研判：无新增决策，交由规则触发器驱动。",
    }


SIMULATOR = SimulatorAgent()
