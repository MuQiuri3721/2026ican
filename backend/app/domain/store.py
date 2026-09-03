from datetime import datetime
from threading import RLock
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4
from pathlib import Path
import json

from .schemas import AnalysisEnvelope, TaskEvent


class AnalysisStore:
    def __init__(self):
        self._items: Dict[str, AnalysisEnvelope] = {}
        self._lock = RLock()

    def create(self, request_data: dict) -> AnalysisEnvelope:
        now = datetime.now().isoformat(timespec="seconds")
        item = AnalysisEnvelope(
            analysis_id="analysis-" + uuid4().hex[:12],
            status="queued",
            created_at=now,
            updated_at=now,
            input=request_data,
        )
        with self._lock:
            self._items[item.analysis_id] = item
        return item.model_copy(deep=True)

    def get(self, analysis_id: str) -> Optional[AnalysisEnvelope]:
        with self._lock:
            item = self._items.get(analysis_id)
            return item.model_copy(deep=True) if item else None

    def list(self) -> List[AnalysisEnvelope]:
        with self._lock:
            return [item.model_copy(deep=True) for item in reversed(list(self._items.values()))]

    def update(self, analysis_id: str, **changes) -> AnalysisEnvelope:
        with self._lock:
            item = self._items.get(analysis_id)
            if item is None:
                raise KeyError("分析任务不存在: " + analysis_id)
            for key in changes:
                if not hasattr(item, key) or key in {"analysis_id", "created_at", "input"}:
                    raise ValueError("不允许更新字段: " + key)
            changes["updated_at"] = datetime.now().isoformat(timespec="seconds")
            for key, value in changes.items():
                setattr(item, key, value)
            return item.model_copy(deep=True)

    def dump(self, analysis_id: str) -> dict:
        item = self.get(analysis_id)
        if item is None:
            raise KeyError("分析任务不存在: " + analysis_id)
        return item.model_dump()

    def monitor_update(self, analysis_id: str, updater: Callable[[AnalysisEnvelope], Dict[str, Any]]) -> AnalysisEnvelope:
        """在同一把锁内完成状态检查、监测计算和结果更新。"""
        with self._lock:
            item = self._items.get(analysis_id)
            if item is None:
                raise KeyError("分析任务不存在: " + analysis_id)
            if item.status in {"completed", "failed", "terminated"}:
                raise ValueError(f"任务已{item.status}，禁止继续监测")
            changes = updater(item.model_copy(deep=True))
            if not isinstance(changes, dict):
                raise ValueError("monitor updater 必须返回字典")
            changes["monitor_round"] = item.monitor_round + 1
            changes["updated_at"] = datetime.now().isoformat(timespec="seconds")
            for key, value in changes.items():
                if key == "updated_at":
                    continue
                if not hasattr(item, key) or key in {"analysis_id", "created_at", "input"}:
                    raise ValueError("不允许更新字段: " + key)
                setattr(item, key, value)
            item.updated_at = changes["updated_at"]
            return item.model_copy(deep=True)

    def add_event(self, analysis_id: str, stage: str, message: str, source: str = "system") -> AnalysisEnvelope:
        with self._lock:
            item = self._items.get(analysis_id)
            if item is None:
                raise KeyError(analysis_id)
            events = [TaskEvent(stage=stage, message=message, source=source), *item.events]
            return self.update(analysis_id, events=events)

    def fleet(self) -> List[dict]:
        path = Path(__file__).resolve().parents[3] / "data" / "fleet.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def inventory(self) -> dict:
        path = Path(__file__).resolve().parents[3] / "data" / "inventory.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def lock_resources(self, analysis_id: str, uav_ids: List[str]) -> List[str]:
        with self._lock:
            item = self._items.get(analysis_id)
            if item is None: raise KeyError(analysis_id)
            active = {uav for other in self._items.values() if other.analysis_id != analysis_id and other.status in {"approved", "executing", "replanning"} for uav in other.resource_locks}
            if active.intersection(uav_ids): raise ValueError("资源已被其他任务锁定")
            item.resource_locks = list(dict.fromkeys(uav_ids))
            return list(item.resource_locks)

    def release_resources(self, analysis_id: str) -> None:
        with self._lock:
            item = self._items.get(analysis_id)
            if item: item.resource_locks = []

    def approval(self, analysis_id: str, action: str, plan_id: Optional[str] = None, constraints: Optional[dict] = None, reason: Optional[str] = None) -> AnalysisEnvelope:
        with self._lock:
            item = self._items.get(analysis_id)
            if item is None: raise KeyError(analysis_id)
            if item.status in {"completed", "terminated", "failed"}: raise ValueError("终态任务禁止审批")
            plan = (item.plan_versions[-1] if item.plan_versions else item.result.get("dispatch_plan") if item.result else None)
            current = plan.get("plan_id") if plan else None
            if plan_id and current and plan_id != current: raise ValueError("方案版本不是当前版本")
            if action == "approve":
                selected = plan.get("selected_uavs", []) if plan else []
                if not selected:
                    selected = [
                        x.get("uav_id")
                        for x in (item.result or {}).get("fleet", [])
                        if x.get("subgroup") == "suppression" or x.get("role") == "firefighting"
                    ][:4]
                if not selected:
                    raise ValueError("当前方案没有可锁定的灭火无人机")
                self.lock_resources(analysis_id, selected)
                status = "approved"
            elif action == "reject": self.release_resources(analysis_id); status = "awaiting_confirmation"
            elif action == "adjust": status = "replanning"
            else: self.release_resources(analysis_id); status = "terminated"
            event = TaskEvent(stage="approval", message=f"方案审批：{action}", source="user")
            item.events = [event, *item.events]; item.approval = {"action": action, "plan_id": current, "constraints": constraints, "reason": reason}
            item.status = status; item.updated_at = datetime.now().isoformat(timespec="seconds")
            return item.model_copy(deep=True)

    def list_events(self, analysis_id: str) -> List[TaskEvent]:
        item = self.get(analysis_id)
        return item.events if item else []


analysis_store = AnalysisStore()
