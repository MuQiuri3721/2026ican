from typing import Any, Dict, Optional

from ..agents.planner import AnalysisPlanner
from ..domain.models import AnalysisPlan, StepStatus
from ..pipeline import run_demo_analysis
from ..tools.registry import ToolRegistry, build_registry


class FireAnalysisSkill:
    """业务 Skill：编排计划和原子 Tool，规则数值仍由 pipeline 负责。"""

    name = "fire_analysis"

    def __init__(self, registry: Optional[ToolRegistry] = None, planner: Optional[AnalysisPlanner] = None):
        self.registry = registry or build_registry()
        self.planner = planner or AnalysisPlanner()

    def run(self, scene_id: str = "forest-demo-01", image_name: Optional[str] = None) -> Dict[str, Any]:
        plan = self.planner.create_plan()
        for step in plan.steps:
            step.status = StepStatus.RUNNING
            if step.id == "ingest":
                step.result = {"image_name": image_name, "accepted": True}
            elif step.id == "vision":
                step.result = {"mode": "demo", "provider": "yolo-pending"}
            elif step.id == "environment":
                step.result = self.registry.execute("get_environment", {"scene_id": scene_id})
            elif step.id == "assessment":
                step.result = {"mode": "rules", "status": "delegated-to-pipeline"}
            elif step.id == "dispatch":
                step.result = {"status": "delegated-to-pipeline"}
            step.status = StepStatus.SUCCEEDED
        return {"plan": plan, "analysis": run_demo_analysis(scene_id, image_name)}


class SkillRegistry:
    def __init__(self, skills: Optional[list] = None):
        self._skills = {skill.name: skill for skill in (skills or [])}

    def register(self, skill: Any) -> None:
        self._skills[skill.name] = skill

    def list(self) -> list:
        return sorted(self._skills)

    def get(self, name: str) -> Any:
        if name not in self._skills:
            raise KeyError("未知 Skill: " + name)
        return self._skills[name]


def build_skill_registry() -> SkillRegistry:
    return SkillRegistry([FireAnalysisSkill()])
