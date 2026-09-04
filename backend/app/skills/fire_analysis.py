from typing import Any, Dict, Optional

from ..agents.plan_executor import PlanExecutor
from ..agents.planner import AnalysisPlanner
from ..pipeline import run_demo_analysis
from ..tools.registry import ToolRegistry, build_registry


class FireAnalysisSkill:
    name = "fire_analysis"
    def __init__(self, registry: Optional[ToolRegistry] = None, planner: Optional[AnalysisPlanner] = None):
        self.registry = registry or build_registry()
        self.planner = planner or AnalysisPlanner()
    def run(self, scene_id: str = "forest-demo-01", image_name: Optional[str] = None) -> Dict[str, Any]:
        context = {}
        if isinstance(scene_id, dict):
            context = scene_id
            scene_id = context.get("scene_id", "forest-demo-01")
            image_name = context.get("image_name")
        plan = self.planner.create_plan()
        handlers = {
            "ingest": lambda context: {"image_name": image_name, "accepted": True},
            "vision": lambda context: {"mode": "demo", "provider": "yolo-pending"},
            "environment": lambda context: self.registry.execute("get_environment", {
                "scene_id": scene_id,
                "latitude": context.get("latitude"),
                "longitude": context.get("longitude"),
                "water_radius_m": context.get("water_search_radius_m", 5000),
                "road_radius_m": context.get("road_search_radius_m", 5000),
                "environment_mode": context.get("environment_mode"),
            }),
            "assessment": lambda context: {"mode": "rules", "status": "delegated-to-pipeline"},
            "dispatch": lambda context: {"status": "delegated-to-pipeline"},
        }
        plan = PlanExecutor().run(plan, handlers, {
            "scene_id": scene_id, "image_name": image_name,
            "latitude": context.get("latitude") if isinstance(context, dict) else None,
            "longitude": context.get("longitude") if isinstance(context, dict) else None,
            "water_search_radius_m": context.get("water_search_radius_m", 5000) if isinstance(context, dict) else 5000,
            "road_search_radius_m": context.get("road_search_radius_m", 5000) if isinstance(context, dict) else 5000,
        })
        return {"plan": plan.as_dict(), "analysis": run_demo_analysis(scene_id, image_name)}


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
