from typing import List

from ..domain.models import AnalysisPlan, PlanStep


class AnalysisPlanner:
    """用固定、可校验的模板生成分析计划，后续可替换为 LLM Planner。"""

    def create_plan(self, goal: str = "完成森林火灾影像研判与无人机调度") -> AnalysisPlan:
        plan = AnalysisPlan(goal=goal, steps=[
            PlanStep("ingest", "接入并校验现场影像"),
            PlanStep("vision", "提取火点与烟雾观测值", ["ingest"]),
            PlanStep("environment", "读取场景环境与水源数据", ["ingest"]),
            PlanStep("assessment", "计算火情风险和资源需求", ["vision", "environment"]),
            PlanStep("dispatch", "校验约束并生成集群调度", ["assessment"]),
        ])
        plan.validate()
        return plan

    @staticmethod
    def ready_steps(plan: AnalysisPlan) -> List[PlanStep]:
        completed = {step.id for step in plan.steps if step.status == "succeeded"}
        return [step for step in plan.steps if step.status == "pending" and set(step.depends_on).issubset(completed)]
