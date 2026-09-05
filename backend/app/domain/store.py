from datetime import datetime
from pathlib import Path
from sqlite3 import connect
from threading import RLock
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4
import json

from .schemas import AnalysisEnvelope, TaskEvent


class AnalysisStore:
    """内存工作态 + SQLite 写穿持久化：重启后任务、方案、事件和锁可恢复。"""

    def __init__(self, db_path: Optional[Path] = None):
        self._items: Dict[str, AnalysisEnvelope] = {}
        # Resource state is owned by the task, never re-read from the global fixture.
        self._fleet_snapshots: Dict[str, List[dict]] = {}
        self._inventory_snapshots: Dict[str, dict] = {}
        self._lock = RLock()
        self._db_path = Path(db_path) if db_path else Path(__file__).resolve().parents[3] / "data" / "analysis_store.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = connect(self._db_path, check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS tasks ("
            "analysis_id TEXT PRIMARY KEY, envelope TEXT NOT NULL, fleet TEXT, inventory TEXT, updated_at TEXT)"
        )
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS agent_messages ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, analysis_id TEXT NOT NULL, seq INTEGER NOT NULL, payload TEXT NOT NULL)"
        )
        self._db.commit()
        self._load_all()

    def _load_all(self) -> None:
        for analysis_id, envelope, fleet, inventory in self._db.execute(
            "SELECT analysis_id, envelope, fleet, inventory FROM tasks"
        ):
            try:
                self._items[analysis_id] = AnalysisEnvelope.model_validate(json.loads(envelope))
                self._fleet_snapshots[analysis_id] = json.loads(fleet) if fleet else []
                self._inventory_snapshots[analysis_id] = json.loads(inventory) if inventory else {}
            except (ValueError, TypeError, json.JSONDecodeError):
                # 历史损坏行跳过，不阻塞启动；合法行仍在。
                continue

    def _persist(self, analysis_id: str) -> None:
        item = self._items.get(analysis_id)
        if item is None:
            return
        self._db.execute(
            "INSERT INTO tasks (analysis_id, envelope, fleet, inventory, updated_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(analysis_id) DO UPDATE SET envelope=excluded.envelope, fleet=excluded.fleet, "
            "inventory=excluded.inventory, updated_at=excluded.updated_at",
            (
                analysis_id,
                item.model_dump_json(),
                json.dumps(self._fleet_snapshots.get(analysis_id, []), ensure_ascii=False),
                json.dumps(self._inventory_snapshots.get(analysis_id, {}), ensure_ascii=False),
                item.updated_at,
            ),
        )
        self._db.commit()

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
            # Import lazily to avoid a pipeline/store import cycle.
            from ..pipeline import load_demo_state
            state = load_demo_state(request_data.get("scene_id", "forest-demo-01"))
            self._fleet_snapshots[item.analysis_id] = self._normalize_fleet(state["fleet"])
            self._inventory_snapshots[item.analysis_id] = self._normalize_inventory(state["inventory"])
            self._persist(item.analysis_id)
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
            self._persist(analysis_id)
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
            self._persist(analysis_id)
            return item.model_copy(deep=True)

    def add_message(self, analysis_id: str, message: Dict[str, Any]) -> Dict[str, Any]:
        """Agent 协作消息（黑板流）：SQLite 写穿，seq 按任务内单调递增。"""
        with self._lock:
            row = self._db.execute(
                "SELECT COALESCE(MAX(seq), 0) FROM agent_messages WHERE analysis_id = ?", (analysis_id,)
            ).fetchone()
            seq = int(row[0]) + 1
            payload = {**message, "seq": seq}
            self._db.execute(
                "INSERT INTO agent_messages (analysis_id, seq, payload) VALUES (?, ?, ?)",
                (analysis_id, seq, json.dumps(payload, ensure_ascii=False, default=str)),
            )
            self._db.commit()
            return payload

    def get_messages(self, analysis_id: str, after_seq: int = 0) -> List[Dict[str, Any]]:
        rows = self._db.execute(
            "SELECT payload FROM agent_messages WHERE analysis_id = ? AND seq > ? ORDER BY seq",
            (analysis_id, after_seq),
        )
        return [json.loads(row[0]) for row in rows]

    def add_event(self, analysis_id: str, stage: str, message: str, source: str = "system") -> AnalysisEnvelope:
        with self._lock:
            item = self._items.get(analysis_id)
            if item is None:
                raise KeyError(analysis_id)
            events = [TaskEvent(stage=stage, message=message, source=source), *item.events]
            return self.update(analysis_id, events=events)

    def fleet(self, analysis_id: Optional[str] = None) -> List[dict]:
        with self._lock:
            if analysis_id:
                if analysis_id not in self._items: raise KeyError(analysis_id)
                return self._normalize_fleet(self._fleet_snapshots.get(analysis_id, []))
            path = Path(__file__).resolve().parents[3] / "data" / "fleet.json"
            return self._normalize_fleet(json.loads(path.read_text(encoding="utf-8")))

    def inventory(self, analysis_id: Optional[str] = None) -> dict:
        with self._lock:
            if analysis_id:
                if analysis_id not in self._items: raise KeyError(analysis_id)
                return self._normalize_inventory(self._inventory_snapshots.get(analysis_id, {}))
            path = Path(__file__).resolve().parents[3] / "data" / "inventory.json"
            return self._normalize_inventory(json.loads(path.read_text(encoding="utf-8")))

    def update_resources(self, analysis_id: str, fleet: Optional[List[dict]] = None, inventory: Optional[dict] = None) -> None:
        with self._lock:
            if analysis_id not in self._items: raise KeyError(analysis_id)
            if fleet is not None:
                self._fleet_snapshots[analysis_id] = self._normalize_fleet(fleet)
            if inventory is not None:
                self._inventory_snapshots[analysis_id] = self._normalize_inventory(inventory)
            self._persist(analysis_id)

    @staticmethod
    def _normalize_fleet(fleet: Any) -> List[dict]:
        from ..pipeline import normalize_fleet
        return json.loads(json.dumps(normalize_fleet(fleet or [])))

    @staticmethod
    def _normalize_inventory(inventory: Any) -> dict:
        from ..pipeline import normalize_inventory
        return json.loads(json.dumps(normalize_inventory(inventory or {})))

    def lock_resources(self, analysis_id: str, uav_ids: List[str]) -> List[str]:
        with self._lock:
            item = self._items.get(analysis_id)
            if item is None: raise KeyError(analysis_id)
            active = {uav for other in self._items.values() if other.analysis_id != analysis_id and other.status in {"approved", "executing", "replanning"} for uav in other.resource_locks}
            if active.intersection(uav_ids): raise ValueError("资源已被其他任务锁定")
            item.resource_locks = list(dict.fromkeys(uav_ids))
            self._persist(analysis_id)
            return list(item.resource_locks)

    def release_resources(self, analysis_id: str) -> None:
        with self._lock:
            item = self._items.get(analysis_id)
            if item: item.resource_locks = []; self._persist(analysis_id)

    def approval(self, analysis_id: str, action: str, plan_id: Optional[str] = None, constraints: Optional[dict] = None, reason: Optional[str] = None, idempotency_key: Optional[str] = None) -> AnalysisEnvelope:
        with self._lock:
            item = self._items.get(analysis_id)
            if item is None: raise KeyError(analysis_id)
            if idempotency_key and item.approval:
                if item.approval.get("idempotency_key") == idempotency_key and item.approval.get("action") == action:
                    return item.model_copy(deep=True)
                # A new action (for example adjust after approve) is a new
                # idempotent command and is allowed to carry a new key.
            if item.status in {"completed", "terminated", "failed"}: raise ValueError("终态任务禁止审批")
            if action == "approve" and item.status not in {"awaiting_confirmation", "replanning", "approved"}:
                raise ValueError("当前任务状态不允许批准")
            if action == "reject" and item.status not in {"awaiting_confirmation", "replanning"}:
                raise ValueError("当前任务状态不允许驳回")
            if action == "adjust" and item.status not in {"awaiting_confirmation", "approved", "executing", "replanning"}:
                raise ValueError("当前任务状态不允许调整")
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
                # Approval is the execution gate: a task is executable immediately
                # after its plan has been locked and approved.
                status = "executing"
            elif action == "reject": self.release_resources(analysis_id); status = "awaiting_confirmation"
            elif action == "adjust":
                # The service generates the replacement plan; never keep locks for
                # a plan which is no longer current.
                self.release_resources(analysis_id)
                status = "replanning"
            else: self.release_resources(analysis_id); status = "terminated"
            event = TaskEvent(stage="approval", message=f"方案审批：{action}", source="user")
            item.events = [event, *item.events]; item.approval = {"action": action, "plan_id": current, "constraints": constraints, "reason": reason, "idempotency_key": idempotency_key}
            item.status = status; item.updated_at = datetime.now().isoformat(timespec="seconds")
            self._persist(analysis_id)
            return item.model_copy(deep=True)

    def list_events(self, analysis_id: str) -> List[TaskEvent]:
        item = self.get(analysis_id)
        return item.events if item else []


analysis_store = AnalysisStore()
