from datetime import datetime
from typing import Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .pipeline import run_demo_analysis, simulate_monitor
from .skills.fire_analysis import build_skill_registry


skill_registry = build_skill_registry()


app = FastAPI(title="Forest Fire Rescue Agent", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://localhost:5174", "http://localhost:5175",
        "http://127.0.0.1:5173", "http://127.0.0.1:5174", "http://127.0.0.1:5175",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    scene_id: str = "forest-demo-01"
    image_path: Optional[str] = None
    image_name: Optional[str] = None
    use_vlm: bool = False


class MonitorRequest(BaseModel):
    elapsed_minutes: float = 5
    extinguishing_liters: float = 40


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "forest-fire-agent", "version": app.version}


@app.get("/api/project-status")
def project_status():
    return {"framework": "ready", "demo_pipeline": "ready", "yolo": "pending", "vlm": "pending", "geo_data": "demo-data", "last_checked": datetime.now().isoformat(timespec="seconds")}


@app.get("/api/tools")
def list_tools():
    return {"tools": skill_registry.get("fire_analysis").registry.list()}


@app.get("/api/skills")
def list_skills():
    return {"skills": skill_registry.list()}


@app.post("/api/skills/{skill_name}/run")
def run_skill(skill_name: str, request: AnalyzeRequest):
    try:
        skill = skill_registry.get(skill_name)
        return {"skill": skill_name, **skill.run(request.scene_id, request.image_name)}
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/analyze/upload")
async def analyze_upload(scene_id: str = "forest-demo-01", use_vlm: bool = False, file: UploadFile = File(...)):
    allowed_types = {"image/jpeg", "image/png", "video/mp4"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=415, detail="仅支持 JPG、PNG 或 MP4 文件")
    content = await file.read()
    if len(content) > 200 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="文件大小不能超过 200MB")
    return {"analysis_id": f"analysis-{datetime.now().strftime('%Y%m%d%H%M%S%f')}", **run_demo_analysis(scene_id, file.filename)}


@app.post("/api/monitor/{analysis_id}")
def monitor(analysis_id: str, request: MonitorRequest):
    if not analysis_id:
        raise HTTPException(status_code=400, detail="缺少分析任务 ID")
    demo = run_demo_analysis("forest-demo-01", None)
    return {"analysis_id": analysis_id, **simulate_monitor(demo, request.elapsed_minutes, request.extinguishing_liters)}


@app.post("/api/analyze")
def analyze(request: AnalyzeRequest):
    try:
        result = run_demo_analysis(request.scene_id, request.image_name or request.image_path)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"analysis_id": f"analysis-{datetime.now().strftime('%Y%m%d%H%M%S')}", **result}
