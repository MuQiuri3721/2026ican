"""⑥ 交互审批 Agent：方案解释（数字来源标注）+ 归档报告消息。"""
from typing import Any, Dict

from ..agentkit.base import BaseAgent
from ..agentkit.llm import audit_numbers
from ..agentkit.prompts import APPROVER_PROMPT
from .blackboard import post_message


class ApproverAgent(BaseAgent):
    agent_id = "approver"
    name = "交互审批"
    role = "system"
    subgroup = "system"
    prompt = APPROVER_PROMPT
    tools: Dict[str, Any] = {}

    def prepare(self, analysis_id: str, result: Dict[str, Any]) -> None:
        fire = result.get("fire_assessment", {})
        dispatch = result.get("dispatch_plan", {})
        gaps = "、".join(gap.get("resource", "") for gap in dispatch.get("resource_gap", []) if gap.get("resource"))
        content = (
            f"方案待审批：{fire.get('label')}，面积 {fire.get('fire_area_m2')}m²，负荷 {fire.get('fire_load_flp')} FLP"
            f"（来源：网格冻结公式）；出动 {(dispatch.get('selected_uavs') or [])}，"
            f"{'预计 ' + str(dispatch.get('estimated_minutes')) + ' 分钟可控' if dispatch.get('can_control') else '超出处置能力，建议增援'}"
            + (f"；缺口：{gaps}" if gaps else "；缺口：无")
        )
        post_message(analysis_id, "APPROVAL_REQ", self.agent_id, "commander", content)
        brief = f"评级{fire.get('label')} 面积{fire.get('fire_area_m2')}m² 负荷{fire.get('fire_load_flp')}FLP 可控{dispatch.get('can_control')}"
        self.think_bg(analysis_id, "向指挥员解释该方案为何值得批准或需要调整，数字原样引用。",
                      brief, lambda aid, text: post_message(aid, "INFO", self.agent_id, "commander", text, source="glm"))


APPROVER = ApproverAgent()
