from datetime import datetime
from threading import RLock
from typing import Dict, List, Optional
from uuid import uuid4

from .schemas import AnalysisEnvelope, TaskEvent


class AnalysisStore:
    def __init__(self):
        self._items: Dict[str, AnalysisEnvelope] = {}
        self._lock = RLock()

    def create(self, request_data: dict) -> AnalysisEnvelope:
        now = datetime.now().isoformat(timespec="seconds")
        item = AnalysisEnvelope(analysis_id="analysis-" + uuid4().hex[:12], status="queued", created_at=now, updated_at=now, input=request_data)
        with self._lock:
            self._items[item.analysis_id] = item
        return item

    def get(self, analysis_id: str) -> Optional[AnalysisEnvelope]:
        with self._lock:
            return self._items.get(analysis_id)

    def list(self) -> List[AnalysisEnvelope]:
        with self._lock:
            return list(reversed(list(self._items.values())))

    def update(self, analysis_id: str, **changes) -> AnalysisEnvelope:
        with self._lock:
            item = self._items.get(analysis_id)
            if item is None:
                raise KeyError("分析任务不存在: " + analysis_id)
            changes["updated_at"] = datetime.now().isoformat(timespec="seconds")
            for key, value in changes.items():
                setattr(item, key, value)
            return item.model_copy(deep=True) if hasattr(item, "model_copy") else item

    def add_event(self, analysis_id: str, stage: str, message: str, source: str = "system") -> AnalysisEnvelope:
        item = self.get(analysis_id)
        if item is None:
            raise KeyError(analysis_id)
        item.events.insert(0, TaskEvent(stage=stage, message=message, source=source))
        return self.update(analysis_id, events=item.events)

    def list_events(self, analysis_id: str) -> List[TaskEvent]:
        item = self.get(analysis_id)
        return item.events if item else []


analysis_store = AnalysisStore()
