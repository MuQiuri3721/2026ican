"""SSE 断线续传（FE-37）：Last-Event-ID 复合游标跳过已投递部分。"""
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.main import app  # noqa: E402


def test_stream_resumes_from_last_event_id():
    client = TestClient(app)
    task = client.post("/api/analyze", json={
        "scene_id": "forest-demo-01", "image_name": "demo.jpg",
        "environment_mode": "offline", "people_status": "absent",
        "scenario": {"fire_origin": {"x": 200, "y": 200}, "fire_area_m2": 900, "growth_rate": 0.2},
    }).json()
    task_id = task["analysis_id"]
    # 产生若干事件
    client.get(f"/api/tasks/{task_id}/plan")
    envelope = client.get(f"/api/analyze/{task_id}").json()
    event_count = len(envelope.get("events") or [])
    assert event_count >= 1, "前置：任务必须已有事件"
    # 断点：e{事件总数}-a0 —— 任务事件应全部跳过，仅剩 agent 消息按 seq 续传
    with client.stream("GET", f"/api/tasks/{task_id}/events/stream?once=1",
                       headers={"Last-Event-ID": f"e{event_count}-a0"}) as response:
        assert response.status_code == 200
        body = b"".join(response.iter_bytes()).decode("utf-8")
    id_lines = [line.split("id: ", 1)[1] for line in body.splitlines() if line.startswith("id: ")]
    assert id_lines, "必须携带 SSE id 行（游标）"
    for cursor in id_lines:
        e_part = cursor.split("-")[0]
        assert int(e_part[1:]) == event_count, f"断点后不得重放旧任务事件（游标 {cursor}）"
    # 对照：不带 Last-Event-ID 时应从头全量
    with client.stream("GET", f"/api/tasks/{task_id}/events/stream?once=1") as response:
        body_full = b"".join(response.iter_bytes()).decode("utf-8")
    full_ids = [line.split("id: ", 1)[1] for line in body_full.splitlines() if line.startswith("id: ")]
    assert full_ids and int(full_ids[0].split("-")[0][1:]) == 1, "无断点时必须从 e1 全量开始"
    client.post(f"/api/tasks/{task_id}/approval", json={"action": "terminate", "reason": "sse test cleanup"})
