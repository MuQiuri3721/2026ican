from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict

from ..domain.models import AnalysisPlan, PlanStep, StepStatus


class PlanExecutor:
    """按依赖拓扑执行计划；同一层无依赖步骤并行。"""

    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers

    def run(self, plan: AnalysisPlan, handlers: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]], context: Dict[str, Any]) -> AnalysisPlan:
        plan.validate()
        steps = {step.id: step for step in plan.steps}
        while True:
            ready = [step for step in steps.values() if step.status == StepStatus.PENDING and all(steps[dep].status == StepStatus.SUCCEEDED for dep in step.depends_on)]
            if not ready:
                break
            with ThreadPoolExecutor(max_workers=min(self.max_workers, len(ready))) as pool:
                futures = {pool.submit(self._execute, step, handlers[step.id], context): step for step in ready}
                for future, step in futures.items():
                    try:
                        step.result = future.result()
                        step.status = StepStatus.SUCCEEDED
                        context[step.id] = step.result
                    except Exception as error:
                        step.status = StepStatus.FAILED
                        step.error = str(error)
                        return plan
        if any(step.status == StepStatus.PENDING for step in steps.values()):
            raise ValueError("计划存在循环依赖或未满足的前置步骤")
        return plan

    @staticmethod
    def _execute(step: PlanStep, handler, context):
        step.status = StepStatus.RUNNING
        return handler(context)
