"""原生轻量任务图（对齐 firepatrol-agents 的图拓扑语义，不引入 LangGraph 依赖）。

拓扑：intake → recon → (suppression ∥ support) → simulator → approver。
2026ican 的轮次环由 API（/rounds）+ 前端推演时钟驱动，审批门禁由 store CAS 承担，
因此图只需覆盖单次研判的编排顺序；条件分支（people=confirmed 追加疏散）在节点内完成。
"""
from typing import Any, Dict, Optional


class MissionGraph:
    def __init__(self, recon, suppression, support):
        self.recon = recon
        self.suppression = suppression
        self.support = support

    def run_analysis_chain(self, state: Dict[str, Any], fire_override: Optional[Dict[str, Any]],
                           people_status: str, constraints: Optional[Dict[str, Any]],
                           fire_type: Optional[str] = None) -> Dict[str, Any]:
        """recon 研判 → suppression 调度；support 分支消息由 support.handle 承担。

        返回 (fire_assessment, dispatch_plan)，结构与迁出前 run_demo_analysis 内联实现完全一致。
        """
        fire = self.recon.assess(state, fire_override)
        if fire_type:
            fire["fire_type"] = fire_type
        dispatch = self.suppression.dispatch(state, fire, people_status, constraints)
        return fire, dispatch
