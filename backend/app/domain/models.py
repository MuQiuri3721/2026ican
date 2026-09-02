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


@dataclass
class AnalysisResult:
    success: bool
    analysis: Dict[str, Any]
    plan: AnalysisPlan
    logs: List[str] = field(default_factory=list)
