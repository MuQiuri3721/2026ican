from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PlanStep:
    id: str
    title: str
    depends_on: List[str] = field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    retries: int = 0


@dataclass
class AnalysisPlan:
    goal: str
    steps: List[PlanStep]

    def validate(self) -> None:
        ids = [step.id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("计划步骤 ID 不能重复")
        known = set(ids)
        for step in self.steps:
            if step.id in step.depends_on:
                raise ValueError("计划步骤不能依赖自身")
            if not set(step.depends_on).issubset(known):
                raise ValueError("计划包含不存在的依赖步骤")
        visiting, visited = set(), set()
        def visit(step_id):
            if step_id in visiting:
                raise ValueError("计划存在循环依赖")
            if step_id in visited:
                return
            visiting.add(step_id)
            for dep in next(step for step in self.steps if step.id == step_id).depends_on:
                visit(dep)
            visiting.remove(step_id)
            visited.add(step_id)
        for step_id in ids:
            visit(step_id)

    def as_dict(self) -> Dict[str, Any]:
        return {"goal": self.goal, "steps": [{"id": step.id, "title": step.title, "depends_on": step.depends_on, "status": step.status.value, "result": step.result, "error": step.error, "retries": step.retries} for step in self.steps]}


@dataclass
class AnalysisResult:
    success: bool
    analysis: Dict[str, Any]
    plan: AnalysisPlan
    logs: List[str] = field(default_factory=list)
