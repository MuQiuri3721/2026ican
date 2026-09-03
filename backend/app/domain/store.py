from datetime import datetime
from threading import RLock
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

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
            if item.status in {"completed", "failed"}:
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

    def list_events(self, analysis_id: str) -> List[TaskEvent]:
        item = self.get(analysis_id)
        return item.events if item else []


analysis_store = AnalysisStore()
