"""④ 支援保障 Agent：有人/无人分支的保障消息。"""
from typing import Any, Dict

from ..agentkit.base import BaseAgent
from ..agentkit.prompts import SUPPORT_PROMPT
from .blackboard import post_message


class SupportAgent(BaseAgent):
    agent_id = "support"
    name = "支援保障"
    role = "support"
    subgroup = "support"
    prompt = SUPPORT_PROMPT
    tools: Dict[str, Any] = {}

    def branch(self, analysis_id: str, people_confirmed: bool, evacuation_text: str = "") -> None:
        if people_confirmed:
            content = "确认有人被困：S 单元建立通信中继并播放疏散广播，疏散路线已并入方案。"
            msg_type = "EVAC_BROADCAST"
        else:
            content = "无人分支：S 单元转入物流补给保障，待命支援灭火单元轮换。"
            msg_type = "INFO"
        post_message(analysis_id, msg_type, self.agent_id, "commander", content + (f" {evacuation_text}" if evacuation_text else ""))


SUPPORT = SupportAgent()
