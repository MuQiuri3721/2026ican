"""任务/平台路由（开发者 A 所有）。

只负责协议、输入校验和 HTTP 错误映射；任务用例统一走 AnalysisService。
"""
import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from ..domain.schemas import AnalysisInput, MonitorInput, ApprovalRequest, ReplanRequest, FeedbackRoundInput
from ..domain.store import analysis_store
from ..services.analysis_service import AnalysisService
from ..skills.orchestrator import SkillExecutionError, SkillOrchestrator
from ..skills.registry import build_skill_registry


skill_registry = build_skill_registry()
skill_orchestrator = SkillOrchestrator(skill_registry)
analysis_service = AnalysisService(skill_orchestrator)
UPLOAD_DIR = Path(__file__).resolve().parents[2] / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
ALLOWED_TYPES = {"image/jpeg", "image/png", "video/mp4"}
router = APIRouter()


def _validate_upload_signature(path: Path, content_type: str) -> None:
    with path.open("rb") as source:
        header = source.read(16)
    valid = {"image/jpeg": header.startswith(b"\xff\xd8\xff"), "image/png": header[:8] == b"\x89PNG\r\n\x1a\n", "video/mp4": b"ftyp" in header[4:16]}
    if not valid.get(content_type, False):
        raise HTTPException(status_code=415, detail=f"文件内容不是有效的 {content_type} 文件")


def _envelope(analysis_id: str) -> dict:
    item = analysis_store.get(analysis_id)
    if item is None:
        raise HTTPException(status_code=404, detail="分析任务不存在")
    return item.model_dump()


@router.get("/api/health")
def health(request: Request):
    return {"status": "ok", "service": "forest-fire-agent", "version": request.app.version}


@router.get("/api/project-status")
def project_status():
    # 新注册表（skills/registry.py）无 fire_analysis 聚合 Skill，Tool 数直接取感知 Skill 的 ToolRegistry。
    perception_registry = skill_registry.get("fire_perception").registry
    return {"framework": "ready", "demo_pipeline": "ready", "agent_layer": "ready", "yolo": "pending", "vlm": "pending", "geo_data": "environment-service", "environment": {"modes": ["auto", "real", "offline", "demo"], "cache": "ttl-lru", "network": "optional"}, "tools": len(perception_registry.list()), "skills": len(skill_registry.list()), "last_checked": datetime.now().isoformat(timespec="seconds")}


@router.get("/api/tools")
def list_tools():
    # 与 project_status 同口径：新注册表（skills/registry.py）无 fire_analysis 聚合 Skill，
    # Tool 列表取感知 Skill 持有的完整 ToolRegistry。
    return {"tools": skill_registry.get("fire_perception").registry.list()}


@router.get("/api/skills")
def list_skills():
    return {"skills": skill_registry.list()}


@router.post("/api/skills/{skill_name}/run")
def run_skill(skill_name: str, request: AnalysisInput):
    try:
        return {"skill": skill_name, **skill_orchestrator.run(skill_name, request.model_dump())}
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/api/fleet")
def fleet(task_id: str | None = None):
    try:
        data = analysis_store.fleet(task_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="任务不存在") from error
    return {"schema_version": "fleet-v1", "fleet": data, "count": len(data), "task_id": task_id}


@router.get("/api/inventory")
def inventory(task_id: str | None = None):
    try:
        data = analysis_store.inventory(task_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="任务不存在") from error
    return {**data, **({"task_id": task_id} if task_id else {})}


@router.get("/api/tasks/{task_id}/plan")
def task_plan(task_id: str):
    try: return analysis_service.get_plan(task_id)
    except KeyError as error: raise HTTPException(status_code=404, detail="任务或方案不存在") from error


@router.post("/api/tasks/{task_id}/approval")
def task_approval(task_id: str, request: ApprovalRequest):
    try: return analysis_service.approve(task_id, request)
    except KeyError as error: raise HTTPException(status_code=404, detail="任务不存在") from error
    except ValueError as error: raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/api/tasks/{task_id}/replan")
def task_replan(task_id: str, request: ReplanRequest):
    try: return analysis_service.replan(task_id, request)
    except KeyError as error: raise HTTPException(status_code=404, detail="任务不存在") from error
    except ValueError as error: raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/api/tasks/{task_id}/rounds")
def task_round(task_id: str, request: FeedbackRoundInput):
    try: return analysis_service.add_round(task_id, request)
    except KeyError as error: raise HTTPException(status_code=404, detail="任务不存在") from error
    except ValueError as error: raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/api/tasks/{task_id}/report")
def task_report(task_id: str):
    try: return analysis_service.report(task_id)
    except KeyError as error: raise HTTPException(status_code=404, detail="任务不存在") from error


@router.get("/api/tasks/{task_id}/report/download")
def download_task_report(task_id: str):
    try:
        path = analysis_service.report_path(task_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="任务不存在") from error
    return FileResponse(path, media_type="application/json", filename="dispatch_plan.json")


@router.get("/api/tasks/{task_id}/events/stream")
async def stream_task_events(task_id: str, once: bool = Query(False)):
    """SSE 事件流：先推全量快照，再增量推送新事件；终态后发送 done 并结束（客户端自动重连可续）。

    `once=1` 时只推送当前快照即结束，供测试与一次性拉取使用。
    """
    if analysis_store.get(task_id) is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    async def event_stream():
        yield "retry: 3000\n\n"
        item = analysis_store.get(task_id)
        if item is None:
            return
        events = item.events
        for event in reversed(events):
            yield f"data: {json.dumps(event.model_dump(), ensure_ascii=False)}\n\n"
        if once:
            yield f"event: done\ndata: {json.dumps({'status': item.status}, ensure_ascii=False)}\n\n"
            return
        sent = len(events)
        idle_ticks = 0
        max_seconds = 300
        while max_seconds > 0:
            item = analysis_store.get(task_id)
            if item is None:
                break
            events = item.events
            total = len(events)
            if total < sent:
                sent = total
            fresh = total - sent
            if fresh:
                for event in reversed(events[:fresh]):
                    yield f"data: {json.dumps(event.model_dump(), ensure_ascii=False)}\n\n"
                sent = total
                idle_ticks = 0
            else:
                idle_ticks += 1
                if idle_ticks % 15 == 0:
                    yield ": keep-alive\n\n"
            if item.status in {"completed", "terminated", "failed"} and total == sent:
                yield f"event: done\ndata: {json.dumps({'status': item.status}, ensure_ascii=False)}\n\n"
                break
            max_seconds -= 1
            await asyncio.sleep(1)

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/api/analyzes")
def list_analyses():
    return {"items": [item.model_dump() for item in analysis_store.list()]}


@router.get("/api/analyze/{analysis_id}")
def get_analysis(analysis_id: str):
    return _envelope(analysis_id)


@router.get("/api/analyze/{analysis_id}/events")
def get_analysis_events(analysis_id: str):
    payload = _envelope(analysis_id)
    return {"analysis_id": analysis_id, "events": payload["events"]}


@router.post("/api/analyze")
def analyze(request: AnalysisInput):
    try:
        return analysis_service.create_and_run(request)
    except (SkillExecutionError, RuntimeError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except (KeyError, ValueError, TypeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/api/analyze/upload")
async def analyze_upload(
    scene_id: str = Form("forest-demo-01"),
    use_vlm: bool = Form(False),
    latitude: float | None = Form(None),
    longitude: float | None = Form(None),
    environment_mode: str | None = Form(None),
    people_status: str = Form("unknown"),
    fire_type: str = Form("vegetation"),
    constraints: str | None = Form(None),
    water_search_radius_m: int = Form(5000, gt=0, le=50000),
    road_search_radius_m: int = Form(5000, gt=0, le=50000),
    file: UploadFile = File(...),
    frames: Optional[List[UploadFile]] = File(default=None),
):
    # 表单通道的 constraints 是 JSON 字符串（multipart 无原生 object 类型），与 §5.1 JSON 体同语义。
    parsed_constraints = None
    if constraints:
        try:
            parsed_constraints = json.loads(constraints)
        except json.JSONDecodeError as error:
            raise HTTPException(status_code=422, detail="constraints 必须是合法 JSON 字符串") from error
        if not isinstance(parsed_constraints, dict):
            raise HTTPException(status_code=422, detail="constraints 必须是 JSON object")
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=415, detail="仅支持 JPG、PNG 或 MP4 文件")
    safe_name = Path(file.filename or "upload.bin").name
    target = UPLOAD_DIR / (uuid4().hex[:12] + "-" + safe_name)
    frame_targets: List[Path] = []
    total = 0
    keep_target = False
    try:
        with target.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="文件大小不能超过 200MB")
                output.write(chunk)
        _validate_upload_signature(target, file.content_type)
        # 多帧序列：逐帧落盘并做同样的类型/魔数校验（api-contract §5.2）。
        frame_paths: List[str] = []
        for frame in frames or []:
            if frame.content_type not in ALLOWED_TYPES:
                raise HTTPException(status_code=415, detail="序列帧仅支持 JPG 或 PNG 文件")
            frame_name = Path(frame.filename or "frame.bin").name
            frame_target = UPLOAD_DIR / (uuid4().hex[:12] + "-" + frame_name)
            frame_total = 0
            with frame_target.open("wb") as output:
                while chunk := await frame.read(1024 * 1024):
                    frame_total += len(chunk)
                    if frame_total > MAX_UPLOAD_BYTES:
                        raise HTTPException(status_code=413, detail="文件大小不能超过 200MB")
                    output.write(chunk)
            _validate_upload_signature(frame_target, frame.content_type)
            frame_targets.append(frame_target)
            frame_paths.append(str(frame_target))
        result = analysis_service.create_and_run(AnalysisInput(scene_id=scene_id, image_name=safe_name, image_path=str(target), use_vlm=use_vlm, latitude=latitude, longitude=longitude, environment_mode=environment_mode, people_status=people_status, fire_type=fire_type, constraints=parsed_constraints, water_search_radius_m=water_search_radius_m, road_search_radius_m=road_search_radius_m), frame_paths=frame_paths or None)
        keep_target = True
        return result
    except (SkillExecutionError, RuntimeError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except (KeyError, ValueError, TypeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    finally:
        await file.close()
        for frame in frames or []:
            await frame.close()
        if not keep_target:
            target.unlink(missing_ok=True)
            for frame_target in frame_targets:
                frame_target.unlink(missing_ok=True)


@router.post("/api/monitor/{analysis_id}")
def monitor(analysis_id: str, request: MonitorInput):
    try:
        return analysis_service.monitor_and_update(analysis_id, request)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
