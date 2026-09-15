"""FE-65 · monitor/replan 幂等键重放防护契约测试。"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend.app.main import app  # noqa: E402


def test_monitor_and_replan_idempotency_keys():
    client = TestClient(app)
    created = client.post("/api/analyze", json={
        "scene_id": "forest-demo-01", "image_name": "idem.jpg",
        "environment_mode": "offline", "people_status": "absent",
        "scenario": {"fire_origin": {"x": 200, "y": 200}, "fire_area_m2": 400, "growth_rate": 0.2},
    })
    assert created.status_code == 200
    task_id = created.json()["analysis_id"]
    plan = client.get(f"/api/tasks/{task_id}/plan").json()["plan"]
    approved = client.post(f"/api/tasks/{task_id}/approval",
                           json={"action": "approve", "plan_id": plan["plan_id"]})
    assert approved.status_code == 200

    # monitor：同键重放返回同一快照，轮次不推进
    body = {"elapsed_minutes": 5, "idempotency_key": "m1"}
    first = client.post(f"/api/monitor/{task_id}", json=body)
    assert first.status_code == 200, first.text
    round_first = first.json()["monitor_round"]
    replay = client.post(f"/api/monitor/{task_id}", json=body)
    assert replay.status_code == 200
    assert replay.json()["monitor_round"] == round_first

    # 不同键 = 新请求，正常推进
    second = client.post(f"/api/monitor/{task_id}",
                         json={"elapsed_minutes": 5, "idempotency_key": "m2"})
    assert second.status_code == 200
    assert second.json()["monitor_round"] == round_first + 1

    # replan：同键重放方案版本不增加
    rp1 = client.post(f"/api/tasks/{task_id}/replan", json={"idempotency_key": "rp1"})
    assert rp1.status_code == 200, rp1.text
    versions_after_first = len(rp1.json()["versions"])
    rp2 = client.post(f"/api/tasks/{task_id}/replan", json={"idempotency_key": "rp1"})
    assert rp2.status_code == 200
    assert len(rp2.json()["versions"]) == versions_after_first
