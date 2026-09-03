from typing import Any, Dict

from ..domain.models import AnalysisPlan
from .registry import SkillRegistry, build_skill_registry


class SkillExecutionError(Exception):
    pass


class SkillOrchestrator:
    """业务门面：按照方案顺序编排 Skill，并保留每一步的结构化结果。"""

    CORE_ORDER = [
        "fire_perception", "environment_assessment", "fire_assessment",
        "people_assessment", "candidate_generation", "constraint_filtering",
        "dispatch_scoring", "route_planning", "approval_preparation",
        "task_execution", "closed_loop_monitoring", "report_archiving",
    ]

    def __init__(self, registry: SkillRegistry = None):
        self.registry = registry or build_skill_registry()

    def run(self, skill_name: str, context: Dict[str, Any]) -> Dict[str, Any]:
        result = self.registry.get(skill_name).run(context)
        if isinstance(result, dict) and result.get("ok") is False:
            raise SkillExecutionError(result.get("error", {}).get("message", "Skill 执行失败"))
        return result

    def run_core_chain(self, context: Dict[str, Any]) -> Dict[str, Any]:
        results = {}
        # Custom/legacy registries may only expose the original chain.
        order = [name for name in self.CORE_ORDER if name in self.registry.list()]
        if not order:
            order = [name for name in self.LEGACY_ORDER if name in self.registry.list()]
        for name in order:
            results[name] = self.run(name, {**context, **results})
            # New planning skills retain the legacy context keys consumed by
            # route/execution/monitoring skills.
            if name == "candidate_generation":
                results.setdefault("resource_matching", results[name].get("resource_matching", {}))
                results.setdefault("drone_dispatch", results[name].get("drone_dispatch", {}))
        return results

    LEGACY_ORDER = [
        "fire_perception", "environment_assessment", "fire_assessment",
        "resource_matching", "drone_dispatch", "route_planning",
        "task_execution", "closed_loop_monitoring",
    ]

    def run_analysis(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """总编排入口：执行 Skill 链，并将规则结果作为最终安全输出。"""
        chain = self.run_core_chain(context)
        return {"skill_chain": chain, "chain_order": self.CORE_ORDER, "data_mode": "demo-stub + rules"}
