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
        result = self.registry.execute("detect_fire", {"image_path": context.get("image_path"), "image_name": context.get("image_name", "default")})
        metrics = self.registry.execute("calculate_fire_metrics", {"detections": result.get("data", {}).get("detections", []), "image_width": result.get("data", {}).get("image_width", 1920), "image_height": result.get("data", {}).get("image_height", 1080)})
        observation = result.get("data", {})
        return {"observation": {"fire_area_m2": observation.get("fire_area_m2", metrics.get("data", {}).get("fire_area_m2", 1800)), "smoke_area_m2": observation.get("smoke_area_m2", metrics.get("data", {}).get("smoke_area_m2", 4200)), "growth_rate": observation.get("growth_rate", 0.42), "confidence": observation.get("confidence", 0.91), "fire_center": observation.get("fire_center", {"x": 118.78, "y": 32.04}), "source": "vision-observation-fixture", "detector": result, "metrics": metrics}}
class EnvironmentAssessmentSkill(BaseSkill):
    name = "environment_assessment"
    def run(self, context):
        scene_id = context.get("scene_id", "forest-demo-01")
        environment = self.registry.execute("get_environment", {
            "scene_id": scene_id,
            "latitude": context.get("latitude"),
            "longitude": context.get("longitude"),
            "water_radius_m": context.get("water_search_radius_m", 3000),
            "road_radius_m": context.get("road_search_radius_m", 3000),
        })
        if not environment.get("ok"): return environment
        scene = environment["data"]
        nearest = scene.get("nearest_water")
        if nearest is None:
            sources = scene.get("water_sources")
            nearest = sources[0] if isinstance(sources, list) and sources else {}
        wind_speed = scene.get("wind_speed") or 0
        wind_direction = scene.get("wind_direction")
        wind_vector = self.registry.execute("calculate_wind_vector", {"wind_speed": wind_speed, "wind_direction_deg": scene.get("wind_direction_deg", 315)})
        spread = self.registry.execute("predict_spread", {"origin": scene.get("fire_origin", {"x": 0, "y": 0}), "wind_vector": wind_vector.get("data", {"x": 0, "y": 0})})
        return {"environment": scene, "environment_source": {"mode": scene.get("mode"), "source": scene.get("source"), "status": scene.get("status")}, "water_sources": {"ok": True, "data": {"sources": scene.get("water_sources", [])}}, "wind_vector": wind_vector, "spread": spread, "nearest_water_distance_m": (nearest or {}).get("distance_m")}
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
        scene_id = context.get("scene_id", "forest-demo-01")
        inventory = self.registry.execute("get_inventory", {"scene_id": scene_id})
        assessment = context.get("fire_assessment", {}).get("assessment", {}).get("data", {})
        environment = context.get("environment_assessment", {})
        need = self.registry.execute("calculate_resource_need", {"fire_area_m2": assessment.get("fire_area_m2", 1800), "level_factor": [0.8, 1.0, 1.35, 1.8][max(1, assessment.get("level", 2)) - 1]})
        material = self.registry.execute("match_extinguisher", {"water_available": bool(environment.get("water_sources", {}).get("data", {}).get("sources")), "inventory_liters": inventory.get("data", {}).get("inventory", {}).get("water_liters", 0)})
        return {"inventory": inventory, "need": need, "material": material}
class DroneDispatchSkill(BaseSkill):
    name = "drone_dispatch"
    def run(self, context):
        fleet = self.registry.execute("get_fleet_status", {"scene_id": context.get("scene_id", "forest-demo-01")})
        need = context.get("resource_matching", {}).get("need", {}).get("data", {})
        candidates = fleet.get("data", {}).get("fleet", [])
        count = self.registry.execute("calculate_drone_count", {"resource_liters": need.get("total_liters", 80), "available_count": len([d for d in candidates if d.get("role") == "firefighting"])})
        assigned = self.registry.execute("assign_tasks", {"fleet": candidates, "required_drones": count.get("data", {}).get("required_drones", 1)})
        tasks = assigned.get("data", {}).get("tasks", [])
        validation = self.registry.execute("validate_plan", {"tasks": tasks, "fleet": candidates, "required_liters": need.get("total_liters", 0)})
        return {"fleet": fleet, "count": count, "assignment": assigned, "validation": validation}
class RoutePlanningSkill(BaseSkill):
    name = "route_planning"
    def run(self, context):
        assignment = context.get("drone_dispatch", {}).get("assignment", {}).get("data", {})
        return {"status": "demo", "route": self.registry.execute("plan_route", {"origin": {"x": 0, "y": 0}, "target": {"x": 800, "y": 0}}), "assigned_tasks": assignment.get("tasks", []), "source": "rules"}
class TaskExecutionSkill(BaseSkill):
    name = "task_execution"
    def run(self, context):
        fire = context.get("fire_perception", {}).get("observation", {})
        resource = context.get("resource_matching", {}).get("need", {}).get("data", {})
        execution = self.registry.execute("execute_firefighting", {"area_m2": fire.get("fire_area_m2", 1800), "extinguishing_liters": min(resource.get("total_liters", 40), 40)})
        return {"status": "simulated", "execution": execution, "message": "未连接真实飞控，仅记录演示执行。"}
class ClosedLoopSkill(BaseSkill):
    name = "closed_loop_monitoring"
    def run(self, context):
        fire = context.get("fire_perception", {}).get("observation", {})
        execution = context.get("task_execution", {}).get("execution", {}).get("data", {})
        growth = self.registry.execute("estimate_growth", {"area_m2": fire.get("fire_area_m2", 1800), "growth_rate": fire.get("growth_rate", 0.42), "wind_speed": context.get("environment_assessment", {}).get("environment", {}).get("wind_speed", 6.5)})
        state = self.registry.execute("update_fire_state", {"area_m2": fire.get("fire_area_m2", 1800), "growth_area_m2": growth.get("data", {}).get("growth_area_m2", 0), "extinguished_area_m2": execution.get("extinguished_area_m2", 0)})
        evaluation = self.registry.execute("evaluate_result", {"previous_area_m2": fire.get("fire_area_m2", 1800), "next_area_m2": state.get("data", {}).get("area_m2", 1800)})
        decision = self.registry.execute("make_next_decision", {"next_area_m2": state.get("data", {}).get("area_m2", 1800), "inventory_liters": context.get("resource_matching", {}).get("inventory", {}).get("data", {}).get("inventory", {}).get("water_liters", 0)})
        return {"growth": growth, "state": state, "evaluation": evaluation, "decision": decision, "source": "rules"}
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
