"""③ 灭火调度 Agent：方案提案 + 出动规模策略（LLM advisory，全枚举对照自检）。"""
import re
from typing import Any, Dict, Optional, Tuple

from ..agentkit.base import BaseAgent
from ..agentkit.llm import audit_numbers
from ..agentkit.prompts import SUPPRESSION_PROMPT
from .blackboard import post_message


class SuppressionAgent(BaseAgent):
    agent_id = "suppression"
    name = "灭火调度"
    role = "suppression"
    subgroup = "suppression"
    prompt = SUPPRESSION_PROMPT
    tools: Dict[str, Any] = {}

    def size_strategy(self, fire: Dict[str, Any], max_drones: int) -> Tuple[Optional[str], str]:
        """LLM 提议出动规模档；仅 advisory——冻结全枚举仿真仍是唯一方案来源。"""
        brief = (f"火情负荷 {fire.get('fire_load_flp')} FLP，增长 {fire.get('growth_flp_per_hour')} FLP/h，"
                 f"可出动上限 {max_drones} 架。只回答出动规模策略，格式 'N-M' 或 'N'。")
        text, _ = self.think("给出出动规模策略。", brief, max_tokens=40)
        if not text:
            return None, "deterministic-offline"
        match = re.search(r"(\d+)\s*(?:-|至|到)\s*(\d+)", text)
        if match:
            low, high = sorted((int(match.group(1)), int(match.group(2))))
            return f"{max(low, 1)}-{min(high, max_drones)}", "glm"
        single = re.search(r"\d+", text)
        if single:
            return single.group(0), "glm"
        return None, "deterministic-offline"

    def dispatch(self, state: Dict[str, Any], fire: Dict[str, Any], people_status: str,
                 constraints: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """调度阶段：唯一分配来源是 rules.deterministic_v1_dispatch（冻结，禁止第二套算法）。"""
        from ..rules.engine import deterministic_v1_dispatch

        return deterministic_v1_dispatch(state, fire, people_status, constraints=constraints)

    def plan(self, analysis_id: str, dispatch: Dict[str, Any], fire: Dict[str, Any],
             strategy: Optional[str], strategy_source: str, max_drones: int) -> None:
        e_units = [u for u in dispatch.get("selected_uavs", []) if str(u).startswith("E")]
        content = (
            f"调度方案 v{dispatch.get('plan_version', 1)}：出动 {len(e_units)} 架灭火机"
            f"（{'、'.join(e_units) or '无'}），负荷 {fire.get('fire_load_flp')} FLP，"
            f"{'可控，预计 ' + str(dispatch.get('estimated_minutes')) + ' 分钟' if dispatch.get('can_control') else '超出能力，建议增援'}。"
        )
        advisory = ""
        if strategy:
            best = len(e_units)
            covered = True
            if "-" in strategy:
                low, high = (int(v) for v in strategy.split("-"))
                covered = low <= best <= high
            elif int(strategy) == best:
                covered = True
            advisory = f" · LLM 建议规模 {strategy}（{strategy_source}）" + ("" if covered else f" · 全枚举最优 {best} 架已自动纳入对照")
        post_message(analysis_id, "PLAN_PROPOSAL", self.agent_id, "commander/approver",
                     content + advisory, {"strategy": strategy, "strategy_source": strategy_source})


SUPPRESSION = SuppressionAgent()
