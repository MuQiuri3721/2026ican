"""① 指挥官 Agent：接警建案、审批后仲裁。"""
from typing import Any, Dict

from ..agentkit.base import BaseAgent
from ..agentkit.prompts import COMMANDER_PROMPT
from .blackboard import post_message


class CommanderAgent(BaseAgent):
    agent_id = "commander"
    name = "指挥官"
    role = "system"
    subgroup = "system"
    prompt = COMMANDER_PROMPT
    tools: Dict[str, Any] = {}

    def intake(self, analysis_id: str, image_label: str, people_label: str) -> None:
        post_message(analysis_id, "TASK_ASSIGN", self.agent_id, "recon/suppression/support",
                     f"接警建案：接收 {image_label}，人员{people_label}。侦察单元赴现场研判，"
                     "灭火与支援单元进入待命。", {"image": image_label, "people": people_label})

    def arbitration(self, analysis_id: str, decision: str, reason: str = "") -> None:
        label = {"approve": "批准出动", "adjust": "按约束调整", "reject": "驳回", "terminate": "终止任务"}.get(decision, decision)
        post_message(analysis_id, "APPROVAL_DECISION", self.agent_id, "all",
                     f"审批仲裁：{label}" + (f" · {reason}" if reason else ""), {"decision": decision})


COMMANDER = CommanderAgent()
