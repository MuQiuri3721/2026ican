import mimetypes
from datetime import datetime
from typing import Optional
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .domain.schemas import AnalysisInput, AnalysisEnvelope, MonitorInput
from .domain.store import analysis_store
from .pipeline import run_demo_analysis, simulate_monitor
from .skills.fire_analysis import build_skill_registry
from .skills.orchestrator import SkillOrchestrator
from .services.analysis_service import AnalysisService


skill_registry = build_skill_registry()
skill_orchestrator = SkillOrchestrator(skill_registry)
analysis_service = AnalysisService(skill_orchestrator)


UPLOAD_DIR = Path(__file__).resolve().parents[2] / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
ALLOWED_TYPES = {"image/jpeg", "image/png", "video/mp4"}
app = FastAPI(title="Forest Fire Rescue Agent", version="0.3.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://localhost:5174", "http://localhost:5175",
        "http://127.0.0.1:5173", "http://127.0.0.1:5174", "http://127.0.0.1:5175",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeRequest(AnalysisInput):
    pass


class MonitorRequest(MonitorInput):
    pass


def _validate_upload_signature(path: Path, content_type: str) -> None:
    with path.open("rb") as source:
        header = source.read(16)
    if content_type == "image/jpeg" and not header.startswith(b"\xff\xd8\xff"):
        raise HTTPException(status_code=415, detail="文件内容不是有效的 JPEG 图片")
    if content_type == "image/png" and header[:8] != b"\x89PNG\r\n\x1a\n":
        raise HTTPException(status_code=415, detail="文件内容不是有效的 PNG 图片")
    if content_type == "video/mp4" and b"ftyp" not in header[4:16]:
        raise HTTPException(status_code=415, detail="文件内容不是有效的 MP4 视频")

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "forest-fire-agent", "version": app.version}


@app.get("/api/project-status")
def project_status():
    return {"framework": "ready", "demo_pipeline": "ready", "agent_layer": "ready", "yolo": "pending", "vlm": "pending", "geo_data": "demo-data", "tools": len(skill_registry.get("fire_analysis").registry.list()), "skills": len(skill_registry.list()), "last_checked": datetime.now().isoformat(timespec="seconds")}


@app.get("/api/tools")
def list_tools():
    return {"tools": skill_registry.get("fire_analysis").registry.list()}


@app.get("/api/skills")
def list_skills():
    return {"skills": skill_registry.list()}


@app.post("/api/skills/{skill_name}/run")
def run_skill(skill_name: str, request: AnalyzeRequest):
    try:
        return {"skill": skill_name, **skill_orchestrator.run(skill_name, {"scene_id": request.scene_id, "image_name": request.image_name, "image_path": request.image_path})}
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/api/analyzes")
def list_analyses():
    items = analysis_store.list()
    return {"items": [item.model_dump() if hasattr(item, "model_dump") else item.dict() for item in items]}


@app.get("/api/analyze/{analysis_id}")
def get_analysis(analysis_id: str):
    item = analysis_store.get(analysis_id)
    if item is None:
        raise HTTPException(status_code=404, detail="分析任务不存在")
    return item.model_dump() if hasattr(item, "model_dump") else item.dict()


@app.get("/api/analyze/{analysis_id}/events")
def get_analysis_events(analysis_id: str):
    item = analysis_store.get(analysis_id)
    if item is None:
        raise HTTPException(status_code=404, detail="分析任务不存在")
    return {"analysis_id": analysis_id, "events": [event.model_dump() if hasattr(event, "model_dump") else event.dict() for event in item.events]}


@app.post("/api/analyze/upload")
async def analyze_upload(scene_id: str = "forest-demo-01", use_vlm: bool = False, file: UploadFile = File(...)):
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=415, detail="仅支持 JPG、PNG 或 MP4 文件")
    safe_name = Path(file.filename or "upload.bin").name
    target = UPLOAD_DIR / (uuid4().hex[:12] + "-" + safe_name)
    target.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with target.open("wb") as output:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                output.close()
                target.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="文件大小不能超过 200MB")
            output.write(chunk)
    _validate_upload_signature(target, file.content_type)
    request = AnalysisInput(scene_id=scene_id, image_name=safe_name, image_path=str(target), use_vlm=use_vlm)
    return analysis_service.create_and_run(request)


def _update_monitor_state(analysis_id: str, item, monitor_result: dict) -> None:
    current = item.result or {}
    fire = dict(current.get("fire_assessment", {}))
    fire["fire_area_m2"] = monitor_result["next_fire_area_m2"]
    updated = dict(current)
    updated["fire_assessment"] = fire
    updated["monitor"] = monitor_result
    if monitor_result["action"] == "finish":
        status = "completed"
    elif monitor_result["action"] in {"return", "resupply"}:
        status = "action_required"
    else:
        status = "running"
    analysis_store.update(analysis_id, status=status, result=updated)


@app.post("/api/monitor/{analysis_id}")
def monitor(analysis_id: str, request: MonitorRequest):
    item = analysis_store.get(analysis_id)
    if item is None or not item.result:
        raise HTTPException(status_code=404, detail="分析任务不存在或尚未完成")
    result = simulate_monitor(item.result, request.elapsed_minutes, request.extinguishing_liters)
    _update_monitor_state(analysis_id, item, result)
    analysis_store.add_event(analysis_id, "monitor", "闭环监测完成：" + result["action"], "rules")
    return {"analysis_id": analysis_id, "status": analysis_store.get(analysis_id).status, **result}


@app.post("/api/analyze")
def analyze(request: AnalyzeRequest):
    return analysis_service.create_and_run(request)


