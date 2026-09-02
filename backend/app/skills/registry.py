from typing import Any, Dict, Optional

from ..tools.registry import ToolRegistry, build_registry


class BaseSkill:
    name = "base_skill"
    status = "demo"
    def __init__(self, registry: Optional[ToolRegistry] = None): self.registry = registry or build_registry()
    def run(self, context: Dict[str, Any]) -> Dict[str, Any]: raise NotImplementedError

class FirePerceptionSkill(BaseSkill):
    name = "fire_perception"
    def run(self, context):
        result = self.registry.execute("detect_fire", {"image_path": context.get("image_path"), "image_name": context.get("image_name")})
        return {"observation": {"fire_area_m2": 1800, "smoke_area_m2": 4200, "growth_rate": 0.42, "confidence": 0.91, "source": "demo-stub", "detector": result}}
class EnvironmentAssessmentSkill(BaseSkill):
    name = "environment_assessment"
    def run(self, context): return self.registry.execute("get_environment", {"scene_id": context.get("scene_id", "forest-demo-01")})
class FireAssessmentSkill(BaseSkill):
    name = "fire_assessment"
    def run(self, context):
        observation = context.get("fire_perception", {}).get("observation", {})
        environment = context.get("environment_assessment", {}).get("data", {})
        result = self.registry.execute("assess_fire_level", {"fire_area_m2": observation.get("fire_area_m2", 1800), "smoke_area_m2": observation.get("smoke_area_m2", 4200), "wind_speed": environment.get("wind_speed", 6.5), "growth_rate": observation.get("growth_rate", 0.42)})
        return {"status": "rules", "assessment": result}
class ResourceMatchingSkill(BaseSkill):
    name = "resource_matching"
    def run(self, context):
        inventory = self.registry.execute("get_inventory", {"scene_id": context.get("scene_id", "forest-demo-01")})
        assessment = context.get("fire_assessment", {}).get("assessment", {})
        need = self.registry.execute("calculate_resource_need", {"fire_area_m2": assessment.get("fire_area_m2", 1800), "level_factor": 1.0})
        return {"inventory": inventory, "need": need}
class DroneDispatchSkill(BaseSkill):
    name = "drone_dispatch"
    def run(self, context):
        fleet = self.registry.execute("get_fleet_status", {"scene_id": context.get("scene_id", "forest-demo-01")})
        need = context.get("resource_matching", {}).get("need", {})
        count = self.registry.execute("calculate_drone_count", {"resource_liters": need.get("total_liters", 80)})
        assigned = self.registry.execute("assign_tasks", {"fleet": fleet.get("data", {}).get("fleet", []), "required_drones": count.get("data", {}).get("required_drones", 1)})
        return {"fleet": fleet, "count": count, "assignment": assigned}
class RoutePlanningSkill(BaseSkill):
    name = "route_planning"
    def run(self, context):
        assignment = context.get("drone_dispatch", {}).get("assignment", {})
        return {"status": "demo", "route": "direct-line", "assigned_tasks": assignment.get("data", {}).get("tasks", []), "source": "demo-stub"}
class TaskExecutionSkill(BaseSkill):
    name = "task_execution"
    def run(self, context): return {"status": "simulated", "message": "未连接真实飞控，仅记录演示执行。"}
class ClosedLoopSkill(BaseSkill):
    name = "closed_loop_monitoring"
    def run(self, context): return {"status": "ready", "next_action": "continue", "source": "rules"}
class EvacuationSkill(BaseSkill):
    name = "evacuation"
    status = "extension"
    def run(self, context): return {"status": "not_implemented", "message": "人群疏散属于扩展能力。"}

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
    return SkillRegistry([klass() for klass in [FirePerceptionSkill, EnvironmentAssessmentSkill, FireAssessmentSkill, ResourceMatchingSkill, DroneDispatchSkill, RoutePlanningSkill, TaskExecutionSkill, ClosedLoopSkill, EvacuationSkill]])
