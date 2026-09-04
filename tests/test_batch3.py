"""批次 3 新能力契约测试：SSE 事件流（A-3）与多帧图片序列（A-4）。"""
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.main import app  # noqa: E402
from backend.app.tools.core import analyze_frame_sequence  # noqa: E402

JPEG_BYTES = b"\xff\xd8\xff" + b"\x00" * 32


def _client() -> TestClient:
    return TestClient(app)


def _create_task(client: TestClient) -> dict:
    response = client.post("/api/analyze", json={"scene_id": "forest-demo-01", "image_name": "demo.jpg", "environment_mode": "offline"})
    assert response.status_code == 200, response.text
    return response.json()


def test_event_stream_sends_snapshot_then_done():
    client = _client()
    task = _create_task(client)
    task_id = task["analysis_id"]

    import json
    with client.stream("GET", f"/api/tasks/{task_id}/events/stream", params={"once": 1}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        data_lines = []
        done_seen = False
        for line in response.iter_lines():
            if line.startswith("data:"):
                data_lines.append(line)
            if line.startswith("event: done"):
                done_seen = True
    assert data_lines, "SSE 快照应至少推送一条事件"
    event = json.loads(data_lines[0][5:].strip())
    assert {"timestamp", "stage", "message", "source"}.issubset(event)
    assert done_seen, "once 模式应在快照后发送 done 并结束"

    assert client.get("/api/tasks/analysis-missing/events/stream").status_code == 404


def test_analyze_frame_sequence_outputs_trend():
    sequence = analyze_frame_sequence([])
    assert sequence["frame_count"] == 0 and sequence["trend"]["status"] == "insufficient_data"


def test_multi_frame_upload_returns_visual_sequence(tmp_path):
    """契约：frames 传早前帧，主文件自动作为最新一帧；无 frames 时不产出 visual_sequence。"""
    client = _client()
    frame_a = tmp_path / "frame-a.jpg"
    frame_b = tmp_path / "frame-b.jpg"
    frame_a.write_bytes(JPEG_BYTES)
    frame_b.write_bytes(JPEG_BYTES)
    response = client.post("/api/analyze/upload", files=[
        ("file", ("frame-b.jpg", JPEG_BYTES, "image/jpeg")),
        ("frames", ("frame-a.jpg", JPEG_BYTES, "image/jpeg")),
    ], data={"scene_id": "forest-demo-01", "environment_mode": "offline"})
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    sequence = result.get("visual_sequence")
    assert sequence and sequence["frame_count"] == 2
    assert sequence["frames"][0]["image_name"].endswith("frame-a.jpg")
    assert sequence["frames"][-1]["image_name"].endswith("frame-b.jpg")
    assert sequence["trend"]["status"] == "ok"

    single = client.post("/api/analyze/upload", files=[("file", ("only.jpg", JPEG_BYTES, "image/jpeg"))], data={"scene_id": "forest-demo-01", "environment_mode": "offline"})
    assert single.status_code == 200
    assert "visual_sequence" not in single.json()["result"]
