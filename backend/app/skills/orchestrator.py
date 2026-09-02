from typing import Dict
from .registry import SkillRegistry, build_skill_registry

class SkillOrchestrator:
    def __init__(self, registry: SkillRegistry = None): self.registry = registry or build_skill_registry()
    def run(self, skill_name: str, context: Dict) -> Dict: return self.registry.get(skill_name).run(context)
    def run_core_chain(self, context: Dict) -> Dict:
        results = {}
        for name in ["fire_perception", "environment_assessment", "fire_assessment", "resource_matching", "drone_dispatch", "route_planning", "task_execution", "closed_loop_monitoring"]:
            results[name] = self.run(name, {**context, **results})
        return results
