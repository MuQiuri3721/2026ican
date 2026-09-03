from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from .domain.schemas import AnalysisInput, MonitorInput, ApprovalRequest, ReplanRequest, FeedbackRoundInput
from .domain.store import analysis_store
from .services.analysis_service import AnalysisService
from .skills.fire_analysis import build_skill_registry
from .skills.orchestrator import SkillExecutionError, SkillOrchestrator
from .tools.environment import EnvironmentTool
from .services.terrain_service import generate_contours


skill_registry = build_skill_registry()
skill_orchestrator = SkillOrchestrator(skill_registry)
analysis_service = AnalysisService(skill_orchestrator)
UPLOAD_DIR = Path(__file__).resolve().parents[2] / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
ALLOWED_TYPES = {"image/jpeg", "image/png", "video/mp4"}
app = FastAPI(title="Forest Fire Rescue Agent", version="0.3.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://localhost:5174", "http://localhost:5175", "http://127.0.0.1:5173", "http://127.0.0.1:5174", "http://127.0.0.1:5175"], allow_methods=["*"], allow_headers=["*"])


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


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "forest-fire-agent", "version": app.version}


@app.get("/api/project-status")
def project_status():
    return {"framework": "ready", "demo_pipeline": "ready", "agent_layer": "ready", "yolo": "pending", "vlm": "pending", "geo_data": "environment-service", "environment": {"modes": ["auto", "real", "offline", "demo"], "cache": "ttl-lru", "network": "optional"}, "tools": len(skill_registry.get("fire_analysis").registry.list()), "skills": len(skill_registry.list()), "last_checked": datetime.now().isoformat(timespec="seconds")}


@app.get("/api/environment")
def environment(
    scene_id: str = "forest-demo-01",
    latitude: float | None = None,
    longitude: float | None = None,
    environment_mode: str | None = None,
    water_radius_m: int = Query(3000, gt=0, le=50000),
    road_radius_m: int = Query(3000, gt=0, le=50000),
):
    try:
        return EnvironmentTool().run(scene_id=scene_id, latitude=latitude, longitude=longitude,
                                     environment_mode=environment_mode, water_radius_m=water_radius_m,
                                     road_radius_m=road_radius_m)
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/api/terrain/contours")
def terrain_contours(
    latitude: float = Query(32.1256451, ge=-90, le=90),
    longitude: float = Query(118.9584748, ge=-180, le=180),
    radius_deg: float = Query(0.04, gt=0, le=0.2),
    interval_m: float = Query(20, ge=1, le=500),
    max_points: int = Query(180, ge=20, le=240),
):
    return generate_contours(latitude, longitude, radius_deg, interval_m, max_points)


@app.get("/api/tools")
def list_tools():
    return {"tools": skill_registry.get("fire_analysis").registry.list()}


@app.get("/api/skills")
def list_skills():
    return {"skills": skill_registry.list()}


@app.post("/api/skills/{skill_name}/run")
def run_skill(skill_name: str, request: AnalysisInput):
    try:
        return {"skill": skill_name, **skill_orchestrator.run(skill_name, request.model_dump())}
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/api/fleet")
def fleet(task_id: str | None = None):
    try:
        data = analysis_store.fleet(task_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="任务不存在") from error
    return {"schema_version": "fleet-v1", "fleet": data, "count": len(data), "task_id": task_id}


@app.get("/api/inventory")
def inventory(task_id: str | None = None):
    try:
        data = analysis_store.inventory(task_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="任务不存在") from error
    return {**data, **({"task_id": task_id} if task_id else {})}


@app.get("/api/tasks/{task_id}/plan")
def task_plan(task_id: str):
    try: return analysis_service.get_plan(task_id)
    except KeyError as error: raise HTTPException(status_code=404, detail="任务或方案不存在") from error


@app.post("/api/tasks/{task_id}/approval")
def task_approval(task_id: str, request: ApprovalRequest):
    try: return analysis_service.approve(task_id, request)
    except KeyError as error: raise HTTPException(status_code=404, detail="任务不存在") from error
    except ValueError as error: raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/tasks/{task_id}/replan")
def task_replan(task_id: str, request: ReplanRequest):
    try: return analysis_service.replan(task_id, request)
    except KeyError as error: raise HTTPException(status_code=404, detail="任务不存在") from error
    except ValueError as error: raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/tasks/{task_id}/rounds")
def task_round(task_id: str, request: FeedbackRoundInput):
    try: return analysis_service.add_round(task_id, request)
    except KeyError as error: raise HTTPException(status_code=404, detail="任务不存在") from error
    except ValueError as error: raise HTTPException(status_code=409, detail=str(error)) from error


@app.get("/api/tasks/{task_id}/report")
def task_report(task_id: str):
    try: return analysis_service.report(task_id)
    except KeyError as error: raise HTTPException(status_code=404, detail="任务不存在") from error


@app.get("/api/tasks/{task_id}/report/download")
def download_task_report(task_id: str):
    try:
        path = analysis_service.report_path(task_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="任务不存在") from error
    return FileResponse(path, media_type="application/json", filename="dispatch_plan.json")


@app.get("/api/analyzes")
def list_analyses():
    return {"items": [item.model_dump() for item in analysis_store.list()]}


@app.get("/api/analyze/{analysis_id}")
def get_analysis(analysis_id: str):
    return _envelope(analysis_id)


@app.get("/api/analyze/{analysis_id}/events")
def get_analysis_events(analysis_id: str):
    payload = _envelope(analysis_id)
    return {"analysis_id": analysis_id, "events": payload["events"]}


@app.post("/api/analyze")
def analyze(request: AnalysisInput):
    try:
        return analysis_service.create_and_run(request)
    except (SkillExecutionError, RuntimeError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except (KeyError, ValueError, TypeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/analyze/upload")
async def analyze_upload(
    scene_id: str = "forest-demo-01",
    use_vlm: bool = False,
    latitude: float | None = None,
    longitude: float | None = None,
    environment_mode: str | None = None,
    water_search_radius_m: int = Query(3000, gt=0, le=50000),
    road_search_radius_m: int = Query(3000, gt=0, le=50000),
    file: UploadFile = File(...),
):
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=415, detail="仅支持 JPG、PNG 或 MP4 文件")
    safe_name = Path(file.filename or "upload.bin").name
    target = UPLOAD_DIR / (uuid4().hex[:12] + "-" + safe_name)
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
        result = analysis_service.create_and_run(AnalysisInput(scene_id=scene_id, image_name=safe_name, image_path=str(target), use_vlm=use_vlm, latitude=latitude, longitude=longitude, environment_mode=environment_mode, water_search_radius_m=water_search_radius_m, road_search_radius_m=road_search_radius_m))
        keep_target = True
        return result
    except (SkillExecutionError, RuntimeError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except (KeyError, ValueError, TypeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    finally:
        await file.close()
        if not keep_target:
            target.unlink(missing_ok=True)


@app.post("/api/monitor/{analysis_id}")
def monitor(analysis_id: str, request: MonitorInput):
    try:
        return analysis_service.monitor_and_update(analysis_id, request)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
