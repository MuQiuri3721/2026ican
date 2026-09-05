"""② 侦察研判 Agent：巡航搜索发现火情（牛耕式航线扫描）+ 火情观测解读。"""
import math
from typing import Any, Dict, Optional

from ..agentkit.base import BaseAgent
from ..agentkit.llm import audit_numbers
from ..agentkit.prompts import RECON_PROMPT
from .blackboard import post_message

# 巡逻航线（FE-28，几何移植自 firepatrol-agents search.py）：牛耕式往返，R1/R2 分扫南北带
SCENE_W, SCENE_H = 2000, 1400
LEGS = (
    {"uav": "R1", "x0": 120, "x1": 1880, "y": 250},
    {"uav": "R2", "x0": 1880, "x1": 120, "y": 650},
    {"uav": "R1", "x0": 120, "x1": 1880, "y": 950},
    {"uav": "R2", "x0": 1880, "x1": 120, "y": 1350},
)


def detect_leg(fire_x: float, fire_y: float, intensity: float):
    """返回 (第几段航线, 航线, 距离 m)：火点进入该段检测半径（380m+60m/强度级）即被发现。"""
    radius = 380 + 60 * max(1, min(4, int(intensity or 2)))
    for index, leg in enumerate(LEGS, 1):
        span = (leg["x1"] - leg["x0"]) or 1.0
        t = max(0.0, min(1.0, ((fire_x - leg["x0"]) * (leg["x1"] - leg["x0"])) / (span * span)))
        dist = math.hypot(fire_x - (leg["x0"] + t * (leg["x1"] - leg["x0"])), fire_y - leg["y"])
        if dist <= radius:
            return index, leg, round(dist)
    return None, None, None


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

    def search_beat(self, analysis_id: str, origin: Optional[Dict[str, Any]], intensity: float) -> None:
        """巡航搜索叙事（FE-28）：按航线几何计算火点在第几段被"发现"，消息按发现时序回放。

        口径说明：2026ican 的研判仍与搜索同批完成（不改变 API 时序），此处是真实航线几何
        的发现过程回放，而非把研判延迟到发现之后。
        """
        try:
            fire_x, fire_y = float(origin.get("x")), float(origin.get("y"))
        except (TypeError, ValueError):
            return
        index, leg, dist = detect_leg(fire_x, fire_y, intensity)
        post_message(analysis_id, "TASK_ASSIGN", "commander", self.agent_id,
                     "巡警搜索：R1/R2 沿牛耕式航线分南北带扫描（2000m×1400m 分区），机载检测持续比对热成像。",
                     {"legs_total": len(LEGS)})
        if index is None:
            post_message(analysis_id, "INFO", self.agent_id, "commander",
                         "四段航线扫描完成，火点未落入检测半径，按烟柱扩散兜底确认火点。", {"coverage": 100})
            return
        coverage = round(index / len(LEGS) * 100)
        post_message(analysis_id, "INFO", self.agent_id, "commander",
                     f"巡航第 {index} 段（{leg['uav']}，扫描带 y={leg['y']}m）：距火点约 {dist}m，"
                     f"进入检测半径，机载检测发现明火与烟柱，已回传指挥中心（覆盖率 {coverage}%）。",
                     {"leg": index, "uav": leg["uav"], "distance_m": dist, "coverage": coverage})

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
