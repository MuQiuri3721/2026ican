from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict

from ..domain.models import AnalysisPlan, PlanStep, StepStatus


class PlanExecutor:
    """按依赖层执行计划，失败时按 max_retries 重试并停止下游。"""

    def __init__(self, max_workers: int = 4, max_retries: int = 1):
        self.max_workers = max_workers
        self.max_retries = max_retries

    def run(self, plan: AnalysisPlan, handlers: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]], context: Dict[str, Any]) -> AnalysisPlan:
        plan.validate()
        steps = {step.id: step for step in plan.steps}
        while True:
            ready = [step for step in steps.values() if step.status == StepStatus.PENDING and all(steps[dep].status == StepStatus.SUCCEEDED for dep in step.depends_on)]
            if not ready:
                break
            with ThreadPoolExecutor(max_workers=min(self.max_workers, len(ready))) as pool:
                futures = {pool.submit(self._run_with_retry, step, handlers[step.id], context): step for step in ready}
                for future, step in futures.items():
                    try:
                        step.result = future.result()
                        step.status = StepStatus.SUCCEEDED
                        context[step.id] = step.result
                    except Exception as error:
                        step.status = StepStatus.FAILED
                        step.error = str(error)
                        for pending in steps.values():
                            if step.id in pending.depends_on and pending.status == StepStatus.PENDING:
                                pending.status = StepStatus.SKIPPED
                        return plan
        if any(step.status == StepStatus.PENDING for step in steps.values()):
            raise ValueError("计划存在循环依赖或未满足的前置步骤")
        return plan

    def _run_with_retry(self, step: PlanStep, handler, context):
        step.status = StepStatus.RUNNING
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                return handler(context)
            except Exception as error:
                last_error = error
                step.retries = attempt + 1
        raise last_error
