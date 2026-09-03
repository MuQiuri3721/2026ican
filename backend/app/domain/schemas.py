from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import AliasChoices, BaseModel, Field, model_validator


class Subgroup(str, Enum):
    RECONNAISSANCE = "reconnaissance"
    SUPPRESSION = "suppression"
    SUPPORT = "support"


class UAVStatus(str, Enum):
    AVAILABLE = "available"
    ASSIGNED = "assigned"
    FLYING = "flying"
    WORKING = "working"
    RETURNING = "returning"
    SERVICING = "servicing"
    CHARGING = "charging"
    FAULT = "fault"


class PayloadModule(str, Enum):
    NONE = "none"
    WATER_20L = "water_20l"
    CO2_6KG = "co2_6kg"
    SUP_10 = "sup_10"


class PeopleStatus(str, Enum):
    CONFIRMED = "confirmed"
    ABSENT = "absent"
    UNKNOWN = "unknown"


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    APPROVED = "approved"
    EXECUTING = "executing"
    REPLANNING = "replanning"
    COMPLETED = "completed"
    TERMINATED = "terminated"
    FAILED = "failed"


class UAVRecord(BaseModel):
    schema_version: str = "uav-v1"
    uav_id: str = Field(min_length=1)
    subgroup: Subgroup
    status: UAVStatus = UAVStatus.AVAILABLE
    position: Dict[str, float] = Field(default_factory=dict)
    soc: float = Field(ge=0, le=100)
    payload_capacity_kg: float = Field(ge=0)
    payload_module: PayloadModule = PayloadModule.NONE
    agent_remaining: float = Field(default=0, ge=0)
    agent_unit: str = "kg"
    speed_mps: float = Field(gt=0)
    energy_rate_percent_per_hour: float = Field(ge=0)
    signal: float = Field(default=100, ge=0, le=100)
    health: float = Field(default=100, ge=0, le=100)
    assigned_task: Optional[str] = None
    last_updated: str = ""

    @model_validator(mode="after")
    def validate_payload(self):
        expected = {PayloadModule.WATER_20L: "L", PayloadModule.CO2_6KG: "kg", PayloadModule.SUP_10: "kg"}
        if self.payload_module in expected and self.agent_unit != expected[self.payload_module]:
            raise ValueError("agent_unit 与 payload_module 不匹配")
        if self.payload_module == PayloadModule.WATER_20L and self.agent_remaining > self.payload_capacity_kg * 1000:
            raise ValueError("水剂载荷超过容量")
        if self.payload_module != PayloadModule.WATER_20L and self.agent_remaining > self.payload_capacity_kg:
            raise ValueError("药剂载荷超过容量")
        return self


class InventorySnapshot(BaseModel):
    schema_version: str = "inventory-v1"
    water_liters: float = Field(default=0, ge=0)
    water_modules_w20: int = Field(default=0, ge=0)
    co2_modules_c6: int = Field(default=0, ge=0)
    support_boxes_sup10: int = Field(default=0, ge=0)
    battery_packs: int = Field(default=0, ge=0)
    forward_supply_points: List[Dict[str, Any]] = Field(default_factory=list)
    water_sources: List[Dict[str, Any]] = Field(default_factory=list)
    dry_powder_kg: float = Field(default=0, ge=0)
    nearby_water_available: bool = False
    last_updated: str = ""


class AnalysisInput(BaseModel):
    scene_id: str = "forest-demo-01"
    image_path: Optional[str] = None
    image_name: Optional[str] = None
    file_id: Optional[str] = None
    use_vlm: bool = False
    fleet_snapshot: str = "default"
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    environment_mode: Optional[str] = None
    water_search_radius_m: int = Field(default=3000, gt=0, le=50000, validation_alias=AliasChoices("water_search_radius_m", "water_radius_m"))
    road_search_radius_m: int = Field(default=3000, gt=0, le=50000, validation_alias=AliasChoices("road_search_radius_m", "road_radius_m"))
    metadata: Optional[Dict[str, Any]] = None
    fire_type: str = "vegetation"
    people_status: PeopleStatus = PeopleStatus.UNKNOWN
    constraints: Optional[Dict[str, Any]] = None


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
    schema_version: str = "analysis-v1"
    plan_versions: List[Dict[str, Any]] = Field(default_factory=list)
    approval: Optional[Dict[str, Any]] = None
    rounds: List[Dict[str, Any]] = Field(default_factory=list)
    resource_locks: List[str] = Field(default_factory=list)


class ApprovalRequest(BaseModel):
    action: str
    plan_id: Optional[str] = None
    constraints: Optional[Dict[str, Any]] = None
    reason: Optional[str] = None
    idempotency_key: Optional[str] = None

    @model_validator(mode="after")
    def validate_action(self):
        if self.action not in {"approve", "reject", "adjust", "terminate"}:
            raise ValueError("action 必须是 approve、reject、adjust 或 terminate")
        return self


class ReplanRequest(BaseModel):
    triggers: List[str] = Field(default_factory=list)
    constraints: Optional[Dict[str, Any]] = None
    observation: Optional[Dict[str, Any]] = None
    people_status: Optional[PeopleStatus] = None


class FeedbackRoundInput(BaseModel):
    round: int = Field(gt=0)
    fire_load_flp: Optional[float] = Field(default=None, ge=0)
    growth_rate: Optional[float] = Field(default=None, ge=0)
    wind_speed: Optional[float] = Field(default=None, ge=0)
    people_status: Optional[PeopleStatus] = None
    fleet_snapshot: Optional[List[Dict[str, Any]]] = None
    inventory: Optional[Dict[str, Any]] = None
    elapsed_minutes: float = Field(default=5, gt=0, le=120)
    extinguishing_liters: float = Field(default=0, ge=0)


class DispatchPlan(BaseModel):
    schema_version: str = "uav-dispatch-v1"
    plan_id: str
    task_id: str
    generated_at: str
    plan_version: int = 1
    risk_level: str = "medium"
    selected_uavs: List[str] = Field(default_factory=list)
    agent_allocation: List[Dict[str, Any]] = Field(default_factory=list)
    battery_plan: List[Dict[str, Any]] = Field(default_factory=list)
    people_branch: PeopleStatus = PeopleStatus.UNKNOWN
    estimated_control_time: Dict[str, Any] = Field(default_factory=dict)
    feasibility: bool = True
    resource_gap: List[Dict[str, Any]] = Field(default_factory=list)
    alternative_plan: List[Dict[str, Any]] = Field(default_factory=list)
    replan_trigger: List[str] = Field(default_factory=list)
