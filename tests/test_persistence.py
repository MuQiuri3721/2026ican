"""AnalysisStore SQLite 持久化契约测试（A-2：重启后任务、事件、锁可恢复）。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.domain.store import AnalysisStore  # noqa: E402


def test_store_survives_restart(tmp_path):
    db = tmp_path / "store.db"
    first = AnalysisStore(db_path=db)
    item = first.create({"scene_id": "forest-demo-01", "image_name": "demo.jpg"})
    task_id = item.analysis_id
    first.update(task_id, status="running")
    first.add_event(task_id, "ingest", "重启前事件")
    first.update_resources(task_id)
    first.lock_resources(task_id, ["E1"])

    # 模拟进程重启：全新实例从同一 SQLite 文件恢复。
    restarted = AnalysisStore(db_path=db)
    restored = restarted.get(task_id)
    assert restored is not None
    assert restored.status == "running"
    assert restored.events and restored.events[0].message == "重启前事件"
    assert restored.resource_locks == ["E1"]
    assert restarted.fleet(task_id)
    assert restarted.inventory(task_id)

    # 恢复后的实例仍可正常推进状态机并再次持久化。
    restarted.release_resources(task_id)
    third = AnalysisStore(db_path=db)
    assert third.get(task_id).resource_locks == []


def test_singleton_store_persists_across_instances(tmp_path):
    db = tmp_path / "store.db"
    AnalysisStore(db_path=db).create({"scene_id": "forest-demo-01", "image_name": "a.jpg"})
    second = AnalysisStore(db_path=db)
    assert len(second.list()) == 1
