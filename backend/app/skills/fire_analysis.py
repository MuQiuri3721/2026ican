from typing import Any, Dict, Optional

from ..agents.planner import AnalysisPlanner
from ..domain.models import StepStatus
from ..pipeline import run_demo_analysis
from ..tools.registry import ToolRegistry, build_registry


class FireAnalysisSkill:
    name = "fire_analysis"
    def __init__(self, registry: Optional[ToolRegistry] = None, planner: Optional[AnalysisPlanner] = None):
        self.registry = registry or build_registry()
        self.planner = planner or AnalysisPlanner()
    def run(self, scene_id: str = "forest-demo-01", image_name: Optional[str] = None) -> Dict[str, Any]:
        plan = self.planner.create_plan()
        tool_environment = self.registry.execute("get_environment", {"scene_id": scene_id})
        if not tool_environment.get("ok"):
            raise ValueError(tool_environment["error"]["message"])
        for step in plan.steps:
            step.status = StepStatus.RUNNING
            if step.id == "ingest": step.result = {"image_name": image_name, "accepted": True}
            elif step.id == "vision": step.result = {"mode": "demo", "provider": "yolo-pending"}
            elif step.id == "environment": step.result = tool_environment["data"]
            elif step.id == "assessment": step.result = {"mode": "rules", "status": "delegated-to-pipeline"}
            elif step.id == "dispatch": step.result = {"status": "delegated-to-pipeline"}
            step.status = StepStatus.SUCCEEDED
        return {"plan": plan, "analysis": run_demo_analysis(scene_id, image_name)}


class SkillRegistry:
    def __init__(self, skills=None): self._skills = {skill.name: skill for skill in (skills or [])}
    def register(self, skill):
        if skill.name in self._skills: raise ValueError("Skill 已注册: " + skill.name)
        self._skills[skill.name] = skill
    def list(self): return sorted(self._skills)
    def get(self, name):
        if name not in self._skills: raise KeyError("未知 Skill: " + name)
        return self._skills[name]


def build_skill_registry():
    from .registry import ClosedLoopSkill, DroneDispatchSkill, EnvironmentAssessmentSkill, EvacuationSkill, FireAssessmentSkill, FirePerceptionSkill, ResourceMatchingSkill, RoutePlanningSkill, TaskExecutionSkill
    return SkillRegistry([FireAnalysisSkill()] + [klass() for klass in [FirePerceptionSkill, EnvironmentAssessmentSkill, FireAssessmentSkill, ResourceMatchingSkill, DroneDispatchSkill, RoutePlanningSkill, TaskExecutionSkill, ClosedLoopSkill, EvacuationSkill]])
