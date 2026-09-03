from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class AnalysisInput(BaseModel):
    scene_id: str = "forest-demo-01"
    image_path: Optional[str] = None
    image_name: Optional[str] = None
    file_id: Optional[str] = None
    use_vlm: bool = False
    fleet_snapshot: str = "default"


class MonitorInput(BaseModel):
    elapsed_minutes: float = Field(default=5, gt=0, le=120)
    extinguishing_liters: float = Field(default=40, ge=0, le=10000)
    image_name: Optional[str] = None
    fleet_snapshot: Optional[List[Dict[str, Any]]] = None
    inventory: Optional[Dict[str, Any]] = None


class TaskEvent(BaseModel):
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    stage: str
    message: str
    source: str = "system"


class AnalysisEnvelope(BaseModel):
    analysis_id: str
    status: str
    created_at: str
    updated_at: str
    input: AnalysisInput
    result: Optional[Dict[str, Any]] = None
    stages: List[Dict[str, Any]] = Field(default_factory=list)
    events: List[TaskEvent] = Field(default_factory=list)
    error: Optional[Dict[str, Any]] = None
    monitor_round: int = 0
