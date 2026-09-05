"""② 侦察研判 Agent：火情观测解读与态势发现。"""
from typing import Any, Dict, Optional

from ..agentkit.base import BaseAgent
from ..agentkit.llm import audit_numbers
from ..agentkit.prompts import RECON_PROMPT
from .blackboard import post_message


class ReconAgent(BaseAgent):
    agent_id = "recon"
    name = "侦察研判"
    role = "reconnaissance"
    subgroup = "reconnaissance"
    prompt = RECON_PROMPT
    tools: Dict[str, Any] = {}

    def assess(self, state: Dict[str, Any], fire_override: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """火情评估阶段：调用 rules.assess_fire（冻结公式，level/label 随实际面积重算）。"""
        from ..rules.engine import assess_fire

        return assess_fire(
            state,
            fire_area=fire_override.get("fire_area_m2") if fire_override else None,
            smoke_area=fire_override.get("smoke_area_m2") if fire_override else None,
            growth_rate=fire_override.get("growth_rate") if fire_override else None,
        )

    def finding(self, analysis_id: str, fire: Dict[str, Any], people_label: str) -> None:
        area = fire.get("fire_area_m2")
        flp = fire.get("fire_load_flp")
        growth = fire.get("growth_rate")
        content = (
            f"火情发现：面积 {area}m²，负荷 {flp} FLP（{fire.get('fire_grid', {}).get('cell_count')} 个 100m² 网格），"
            f"增长率 {growth}/h，评级 {fire.get('label')}，人员{people_label}。"
        )
        post_message(analysis_id, "FINDING", self.agent_id, "suppression/support",
                     content, {"fire_area_m2": area, "fire_load_flp": flp, "label": fire.get("label")})
        brief = f"面积{area}m² 负荷{flp}FLP 增长{growth} 评级{fire.get('label')} 人员{people_label}"
        self.think_bg(analysis_id, "用两句话解读当前火情态势与主要风险。", brief,
                      lambda aid, text: post_message(aid, "INFO", self.agent_id, "commander", text, source="glm"))


RECON = ReconAgent()
