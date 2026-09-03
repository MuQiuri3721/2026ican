from datetime import datetime
from typing import Any, Dict, Optional
from uuid import uuid4

from ..domain.schemas import AnalysisInput
from ..domain.store import analysis_store
from ..pipeline import run_demo_analysis
from ..skills.orchestrator import SkillOrchestrator


class AnalysisService:
    """统一分析应用服务：所有入口共享同一份任务、规则和 Agent 链结果。"""

    def __init__(self, orchestrator: Optional[SkillOrchestrator] = None):
        self.orchestrator = orchestrator or SkillOrchestrator()

    def create_and_run(self, request: AnalysisInput) -> Dict[str, Any]:
        item = analysis_store.create(request.model_dump() if hasattr(request, "model_dump") else request.dict())
        analysis_store.update(item.analysis_id, status="running")
        analysis_store.add_event(item.analysis_id, "ingest", "影像输入已接收", "upload" if request.image_path else "api")
        try:
            context = {"scene_id": request.scene_id, "image_name": request.image_name or "default", "image_path": request.image_path}
            agent = self.orchestrator.run_analysis(context)
            result = run_demo_analysis(request.scene_id, request.image_name or request.image_path)
            self._merge_agent_result(result, agent)
            analysis_store.update(item.analysis_id, status="succeeded", result=result, stages=result.get("pipeline_stages", []))
            analysis_store.add_event(item.analysis_id, "dispatch", "分析链完成并生成调度方案", "rules")
        except (KeyError, ValueError) as error:
            analysis_store.update(item.analysis_id, status="failed", error={"error_code": "analysis_failed", "message": str(error), "stage": "agent_chain"})
            raise
        return analysis_store.get(item.analysis_id).model_dump() if hasattr(analysis_store.get(item.analysis_id), "model_dump") else analysis_store.get(item.analysis_id).dict()

    @staticmethod
    def _merge_agent_result(result: Dict[str, Any], agent: Dict[str, Any]) -> None:
        chain = agent.get("skill_chain", {})
        result["agent"] = agent
        observation = chain.get("fire_perception", {}).get("observation", {})
        assessment = chain.get("fire_assessment", {}).get("assessment", {}).get("data", {})
        if observation:
            result["fire_assessment"].update({key: observation[key] for key in ("fire_area_m2", "smoke_area_m2", "growth_rate", "confidence") if key in observation})
        if assessment:
            result["fire_assessment"].update({key: assessment[key] for key in ("level", "label", "risk_score") if key in assessment})
        resource = chain.get("resource_matching", {}).get("need", {}).get("data", {})
        assignment = chain.get("drone_dispatch", {}).get("assignment", {}).get("data", {})
        if resource:
            result["dispatch_plan"].update({"material_amount": resource.get("total_liters", result["dispatch_plan"].get("material_amount")), "required_drones": chain.get("drone_dispatch", {}).get("count", {}).get("data", {}).get("required_drones", 1)})
        if assignment:
            result["dispatch_plan"]["tasks"] = assignment.get("tasks", result["dispatch_plan"].get("tasks", []))
        result["data_mode"] = agent.get("data_mode", result.get("data_mode"))
