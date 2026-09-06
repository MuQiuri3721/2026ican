import math
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
        scenario = context.get("scenario")
        if scenario:
            # 演训模拟（FE-18）：跳过影像识别，由场景参数直接合成观测
            area = float(scenario.get("fire_area_m2") or 800)
            return {"observation": {
                "fire_area_m2": area,
                "smoke_area_m2": round(area * 2.33, 1),
                "growth_rate": float(scenario.get("growth_rate") or 0.42),
                "confidence": 0.9,
                "fire_center": context.get("fire_center") or {"latitude": 32.0688, "longitude": 118.8432},
                "detector": "scenario-synthetic",
                "source": "演训模拟随机火情",
            }}
        result = self.registry.execute("detect_fire", {"image_path": context.get("image_path"), "image_name": context.get("image_name", "default"), "strict_real": context.get("strict_real", False)})
        detector_data = result.get("data") if isinstance(result.get("data"), dict) else {}
        if not result.get("ok") or detector_data.get("status") == "error":
            return {"ok": False, "status": "error", "error": detector_data.get("error") or result.get("error"), "source": detector_data.get("source", "detector")}
        metrics = self.registry.execute("calculate_fire_metrics", {"detections": detector_data.get("detections", []), "image_width": detector_data.get("image_width", 1920), "image_height": detector_data.get("image_height", 1080)})
        metrics_data = metrics.get("data") if isinstance(metrics.get("data"), dict) else {}
        observation = detector_data
        explanation = {}
        explanation_result = None
        if context.get("use_vlm", True):
            explanation_result = self.registry.execute("analyze_with_vlm", {"observation": observation, "environment": (context.get("environment_assessment") or {}).get("environment", {}), "people_status": context.get("people_status", "unknown"), "strict_real": context.get("strict_real", False), "image_paths": context.get("image_paths"), "task_id": context.get("task_id"), "round_index": context.get("round_index", 1)})
            explanation = explanation_result.get("data") if isinstance(explanation_result.get("data"), dict) else {}
            if explanation.get("status") == "error":
                explanation = {}  # strict_real 失败的错误对象不进解释链（BE-11：避免前端把错误渲染成空 VLM 注释）
        return {"observation": {"fire_area_m2": observation.get("fire_area_m2", metrics_data.get("fire_area_m2", 1800)), "smoke_area_m2": observation.get("smoke_area_m2", metrics_data.get("smoke_area_m2", 4200)), "growth_rate": observation.get("growth_rate", 0.42), "confidence": observation.get("confidence", 0.91), "fire_center": context.get("fire_center") or observation.get("fire_center") or {"latitude": 32.04, "longitude": 118.78}, "source": observation.get("source", "vision-observation-fixture"), "detector": result, "metrics": metrics}, "explanation": explanation, "vlm_used": bool(context.get("use_vlm", True))}
class EnvironmentAssessmentSkill(BaseSkill):
    name = "environment_assessment"
    def run(self, context):
        scene_id = context.get("scene_id", "forest-demo-01")
        environment = self.registry.execute("get_environment", {
            "scene_id": scene_id,
            "latitude": context.get("latitude"),
            "longitude": context.get("longitude"),
            "water_radius_m": context.get("water_search_radius_m", 5000),
            "road_radius_m": context.get("road_search_radius_m", 5000),
            "environment_mode": context.get("environment_mode"),
            "metadata": context.get("metadata"),
        })
        if not environment.get("ok"): return environment
        scene = environment["data"]
        if scene.get("status") == "error" and context.get("strict_real"):
            return {"ok": False, "error": scene.get("error", {"code": "environment_unavailable", "message": "真实环境服务不可用"}), "environment": scene, "environment_source": {"mode": scene.get("mode"), "source": scene.get("source"), "status": scene.get("status")}}
        nearest = scene.get("nearest_water")
        if nearest is None:
            sources = scene.get("water_sources")
            nearest = sources[0] if isinstance(sources, list) and sources else {}
        wind_speed = scene.get("wind_speed") or 0
        wind_direction = scene.get("wind_direction")
        wind_vector = self.registry.execute("calculate_wind_vector", {"wind_speed": wind_speed, "wind_direction_deg": scene.get("wind_direction_deg", 315)})
        spread = self.registry.execute("predict_spread", {"origin": scene.get("fire_origin", {"x": 0, "y": 0}), "wind_vector": wind_vector.get("data", {"x": 0, "y": 0})})
        water_sources = scene.get("water_sources", [])
        water_ok = scene.get("mode") == "demo" or bool(water_sources)
        return {"environment": scene, "environment_source": {"mode": scene.get("mode"), "source": scene.get("source"), "status": scene.get("status"), "stale": scene.get("stale", False), "location": scene.get("location")}, "water_sources": {"ok": water_ok, "data": {"sources": water_sources}, "source": scene.get("source")}, "wind_vector": wind_vector, "spread": spread, "nearest_water_distance_m": (nearest or {}).get("distance_m")}
class FireAssessmentSkill(BaseSkill):
    name = "fire_assessment"
    def run(self, context):
        observation = context.get("fire_perception", {}).get("observation", {})
        environment_result = context.get("environment_assessment", {})
        environment = environment_result.get("environment") or environment_result.get("data") or {}
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
        target = context.get("candidate_generation", {}).get("fire_origin") or {"x": 800, "y": 0}
        route = self.registry.execute("plan_route", {"origin": {"x": 0, "y": 0}, "target": target})
        return {"status": "rules", "route": route, "assigned_tasks": assignment.get("tasks", []), "source": "rules"}
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
    def run(self, context):
        """有人分支的确定性疏散路线：以火点为中心封闭风险网格，BFS 规避后输出路径与预估时间。

        风险半径由火情面积等效圆换算为网格数（api-contract §6 坐标口径：米制相对坐标）。
        """
        candidate = context.get("candidate_generation", {})
        origin = candidate.get("fire_origin") or {"x": 0, "y": 0}
        fire_area = float(context.get("fire_perception", {}).get("observation", {}).get("fire_area_m2", 1800) or 1800)
        grid_cols = grid_rows = 12
        cell_meters = 40
        center = (grid_cols // 2, grid_rows // 2)
        radius_cells = max(1, math.ceil(math.sqrt(max(fire_area, 1) / math.pi) / cell_meters))
        blocked = [
            [col, row]
            for row in range(grid_rows)
            for col in range(grid_cols)
            if math.hypot(col - center[0], row - center[1]) <= radius_cells
        ]
        start = [max(0, center[0] - radius_cells - 1), center[1]]
        if start in blocked:
            start = [0, 0]
        route = self.registry.execute("plan_evacuation_route", {
            "start": start, "exit_cell": [grid_cols - 1, grid_rows - 1], "blocked": blocked,
            "grid_cols": grid_cols, "grid_rows": grid_rows, "cell_meters": cell_meters,
        })
        data = route.get("data", {})
        return {
            "status": "ok" if data.get("found") else "blocked",
            "people_branch": context.get("people_status", "unknown"),
            "fire_origin": origin,
            "risk_cells": len(blocked),
            "start": start,
            **data,
            "source": "rules",
        }

class PeopleAssessmentSkill(BaseSkill):
    name = "people_assessment"
    def run(self, context):
        status = context.get("people_status", "unknown")
        if status not in {"confirmed", "absent", "unknown"}: status = "unknown"
        return {"status": status, "confirmed": status != "unknown", "requires_confirmation": status == "unknown", "source": "user-or-fallback"}


class CandidateGenerationSkill(BaseSkill):
    name = "candidate_generation"
    def run(self, context):
        """Generate candidates exclusively through the deterministic V1 dispatcher.

        The surrounding skills may enrich perception/environment context, but they
        must not introduce a second assignment algorithm.  The returned legacy
        keys are adapters for older downstream skills and API consumers.
        """
        from ..pipeline import deterministic_v1_dispatch, load_demo_state, normalize_fleet, normalize_inventory

        state = load_demo_state(context.get("scene_id", "forest-demo-01"))
        scenario = context.get("scenario")
        if scenario and scenario.get("fire_origin"):
            # 演训模拟（FE-18）：随机火点覆盖框架原点，出动距离随之变化
            state["scene"]["fire_origin"] = dict(scenario["fire_origin"])
        if context.get("fleet"):
            state["fleet"] = normalize_fleet(context["fleet"])
        if context.get("inventory"):
            state["inventory"] = normalize_inventory(context["inventory"])
        perception = context.get("fire_perception", {}).get("observation", {})
        assessment = context.get("fire_assessment", {}).get("assessment", {}).get("data", {})
        environment = context.get("environment_assessment", {}).get("environment", {})
        fire = {
            **perception,
            **assessment,
            "fire_type": context.get("fire_type", "vegetation"),
            "wind_speed": environment.get("wind_speed", state["scene"].get("wind_speed", 0)),
        }
        # FLP 必须由网格公式计算（与 pipeline assess_fire 同一冻结公式），
        # 不能退化成 fire_area/常数——audit §三.1 与 api-contract §8 的要求。
        if not fire.get("fire_load_flp"):
            grid = self.registry.execute("build_fire_grid", {
                "fire_area_m2": fire.get("fire_area_m2", 1800),
                "wind_speed": fire.get("wind_speed", 0),
                "slope_deg": state["scene"].get("slope_deg", 12),
                "fuel_type": state["scene"].get("fuel_type", "general_forest"),
                "intensity": min(4, max(1, assessment.get("level", 2))),
            })
            grid_data = grid.get("data", {})
            fire["fire_load_flp"] = grid_data.get("fire_load_flp")
            fire["fire_grid"] = {key: grid_data[key] for key in ("cell_area_m2", "cell_count", "intensity", "k_fuel", "k_wind", "k_slope", "fuel_type")}
            fire["growth_flp_per_hour"] = round(float(fire["fire_load_flp"]) * float(fire.get("growth_rate", 0.42)), 2)
        plan = deterministic_v1_dispatch(
            state,
            fire,
            context.get("people_status", "unknown"),
            constraints=context.get("constraints"),
        )
        tasks = plan.get("tasks", [])
        legacy_resource = {"need": {"data": {"total_liters": plan.get("material_amount", 0)}}, "source": "v1-dispatch"}
        legacy_dispatch = {
            "fleet": {"data": {"fleet": state["fleet"]}},
            "count": {"data": {"required_drones": plan.get("required_drones", 1)}},
            "assignment": {"data": {"tasks": tasks}},
            "validation": {"data": {"valid": plan.get("feasibility", False), "errors": [g for g in plan.get("resource_gap", []) if g.get("resource_gap")]}},
            "v1_plan": plan,
        }
        return {
            "v1_dispatch": plan,
            "fire_origin": state["scene"].get("fire_origin", {"x": 0, "y": 0}),
            "resource_matching": legacy_resource,
            "drone_dispatch": legacy_dispatch,
            "candidates": tasks,
            "selected_uavs": plan.get("selected_uavs", []),
            "source": "deterministic-v1",
        }


class ConstraintFilteringSkill(BaseSkill):
    name = "constraint_filtering"
    def run(self, context):
        candidate = context.get("candidate_generation", {})
        plan = candidate.get("v1_dispatch", {})
        errors = [gap for gap in plan.get("resource_gap", []) if gap.get("resource_gap")]
        return {"valid": bool(plan.get("feasibility", False)), "errors": errors, "candidates": candidate.get("candidates", []), "plan": plan, "source": "hard-constraints"}


class DispatchScoringSkill(BaseSkill):
    name = "dispatch_scoring"
    def run(self, context):
        plan = context.get("constraint_filtering", {}).get("plan") or context.get("candidate_generation", {}).get("v1_dispatch", {})
        return {"score": (plan.get("scoring", {}).get("chosen", {}).get("score") if isinstance(plan.get("scoring"), dict) else None), "lower_is_better": True, "candidate_count": len(context.get("candidate_generation", {}).get("candidates", [])), "selected": plan, "source": "rules"}


class ApprovalPreparationSkill(BaseSkill):
    name = "approval_preparation"
    def run(self, context):
        people = context.get("people_assessment", {})
        constraints = context.get("constraint_filtering", {})
        return {"status": "awaiting_confirmation", "requires_user_confirmation": True, "people_confirmed": people.get("confirmed", False), "constraints_valid": constraints.get("valid", True), "plan": context.get("dispatch_scoring", {}).get("selected", {}), "source": "rules"}


class ReportArchivingSkill(BaseSkill):
    name = "report_archiving"
    def run(self, context):
        return {"status": "archived", "skill_count": len(context), "chain_keys": sorted(context), "source": "in-memory-report"}
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
    return SkillRegistry([klass() for klass in [FirePerceptionSkill, EnvironmentAssessmentSkill, FireAssessmentSkill, PeopleAssessmentSkill, CandidateGenerationSkill, ConstraintFilteringSkill, DispatchScoringSkill, ApprovalPreparationSkill, ResourceMatchingSkill, DroneDispatchSkill, RoutePlanningSkill, TaskExecutionSkill, ClosedLoopSkill, ReportArchivingSkill, EvacuationSkill]])
