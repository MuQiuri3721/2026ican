"""任务/平台路由（开发者 A 所有）。

只负责协议、输入校验和 HTTP 错误映射；任务用例统一走 AnalysisService。
"""
import asyncio
import json
import re
import os
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
    # 接入状态按环境变量如实上报（api-contract §10/§9）：配置了端点/Key 即"已配置"，未配置为"待接入"。
    yolo_status = "configured" if os.environ.get("FIRE_YOLO_ENDPOINT") else "pending"
    vlm_status = "configured" if (os.environ.get("FIRE_VLM_ENDPOINT") or os.environ.get("FIRE_VLM_API_KEY")) else "pending"
    return {"framework": "ready", "demo_pipeline": "ready", "agent_layer": "ready", "yolo": yolo_status, "vlm": vlm_status, "geo_data": "environment-service", "environment": {"modes": ["auto", "real", "offline", "demo"], "cache": "ttl-lru", "network": "optional"}, "tools": len(perception_registry.list()), "skills": len(skill_registry.list()), "last_checked": datetime.now().isoformat(timespec="seconds")}


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
    except SkillExecutionError as error:
        # 契约 §6.2：Skill 内部失败（ok:false）映射 502，不得裸 500。
        raise HTTPException(status_code=502, detail=str(error)) from error
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
async def stream_task_events(task_id: str, once: bool = Query(False), request: Request = None):
    """SSE 事件流：先推全量快照，再增量推送新事件；终态后发送 done 并结束（客户端自动重连可续）。

    `once=1` 时只推送当前快照即结束，供测试与一次性拉取使用。
    断线续传（FE-37）：浏览器 EventSource 重连自动携带 Last-Event-ID；复合游标
    `e{事件下标}-a{消息seq}` 同时携带两条流的读取位置，服务端据此跳过已投递部分。
    """
    if analysis_store.get(task_id) is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    last_id = (request.headers.get("last-event-id") if request else "") or ""
    resume_match = re.match(r"e(\d+)-a(\d+)", last_id)
    resume_event = int(resume_match.group(1)) if resume_match else 0
    resume_agent = int(resume_match.group(2)) if resume_match and resume_match.group(2) else 0

    async def event_stream():
        yield "retry: 3000\n\n"
        item = analysis_store.get(task_id)
        if item is None:
            return
        events = item.events
        start = max(0, min(resume_event, len(events)))
        for index in range(start, len(events)):
            yield f"id: e{index + 1}-a{resume_agent}\ndata: {json.dumps(events[index].model_dump(), ensure_ascii=False)}\n\n"
        msg_seq = resume_agent
        for message in analysis_store.get_messages(task_id, after_seq=msg_seq):
            msg_seq = message["seq"]
            yield f"id: e{len(events)}-a{msg_seq}\nevent: agent_message\ndata: " + json.dumps(message, ensure_ascii=False) + "\n\n"
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
                for offset, event in enumerate(reversed(events[:fresh])):
                    yield f"id: e{sent + fresh - offset}-a{msg_seq}\ndata: {json.dumps(event.model_dump(), ensure_ascii=False)}\n\n"
                sent = total
                idle_ticks = 0
            fresh_messages = analysis_store.get_messages(task_id, after_seq=msg_seq)
            if fresh_messages:
                for message in fresh_messages:
                    msg_seq = message["seq"]
                    yield f"id: e{sent}-a{msg_seq}\nevent: agent_message\ndata: " + json.dumps(message, ensure_ascii=False) + "\n\n"
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


@router.get("/api/tasks/{task_id}/agent-messages")
def agent_messages(task_id: str, after_seq: int = 0):
    if analysis_store.get(task_id) is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"items": analysis_store.get_messages(task_id, after_seq)}


@router.get("/api/scenarios/random")
def random_scenario():
    from ..domain.scenarios import random_scenario as _random
    return _random()


@router.get("/api/llm-status")
def llm_status():
    from ..agentkit import llm_status as _llm_status
    return _llm_status()


@router.get("/api/analyzes")
def list_analyses(limit: int | None = Query(None, gt=0, le=1000), slim: bool = Query(False)):
    """任务列表。`limit` 截取最新 N 条；`slim=1` 只返回列表页摘要字段（不含 result 等重负载），
    完整信封经 /api/analyze/{id} 按需获取——历史页曾因全量信封在数百任务下拖慢首屏。"""
    items = analysis_store.list()
    if limit is not None:
        items = items[:limit]
    if slim:
        keys = ("analysis_id", "status", "created_at", "updated_at", "monitor_round", "resource_locks", "input")
        items = [{key: value for key, value in item.model_dump().items() if key in keys} for item in items]
    return {"items": items}


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
