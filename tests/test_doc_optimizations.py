"""按文档优化项测试（实现差异审计§六.3 位置变化、§八 输入 hash 溯源、§九 轮次动作展示）。

- analyze_visual_trend / analyze_frame_sequence：帧序列火点位置变化（center_delta_m）
- create_and_run：input_provenance 输入文件 hash（SHA-256 前 16 位）
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.tools.core import analyze_frame_sequence, analyze_visual_trend  # noqa: E402
from backend.app.services.analysis_service import _file_sha16  # noqa: E402


def test_visual_trend_reports_center_movement():
    rows = [
        {"fire_area_m2": 100, "fire_center": {"x": 118.78, "y": 32.04}},
        {"fire_area_m2": 130, "fire_center": {"x": 118.782, "y": 32.041}},
        {"fire_area_m2": 150, "fire_center": {"x": 118.785, "y": 32.043}},
    ]
    trend = analyze_visual_trend(rows)
    assert trend["status"] == "ok" and trend["trend"] == "growing"
    assert trend["center_delta_m"] > 400  # 约 0.005°/0.003° 位移 → 数百米
    assert trend["first_center"] == {"x": 118.78, "y": 32.04}
    assert trend["last_center"] == {"x": 118.785, "y": 32.043}


def test_visual_trend_without_centers_omits_movement():
    trend = analyze_visual_trend([{"fire_area_m2": 100}, {"fire_area_m2": 120}])
    assert trend["status"] == "ok"
    assert "center_delta_m" not in trend


def test_frame_sequence_carries_fire_center(tmp_path, monkeypatch):
    import backend.app.tools.core as core

    def fake_detect(image_name="", image_path=None, **_):
        return {"fire_area_m2": 100.0, "smoke_area_m2": 200.0,
                "fire_center": {"x": 118.78, "y": 32.04}, "confidence": 0.9}

    monkeypatch.setattr(core, "detect_fire", fake_detect)
    result = core.analyze_frame_sequence([str(tmp_path / "a.jpg"), str(tmp_path / "b.jpg")])
    assert result["frame_count"] == 2
    assert result["frames"][0]["fire_center"] == {"x": 118.78, "y": 32.04}
    assert result["trend"]["center_delta_m"] is not None or "center_delta_m" not in result["trend"]


def test_file_sha16_matches_known_vector(tmp_path):
    target = tmp_path / "frame.jpg"
    target.write_bytes(b"hello world")
    import hashlib
    expected = hashlib.sha256(b"hello world").hexdigest()[:16]
    assert _file_sha16(str(target)) == expected
    assert _file_sha16(str(tmp_path / "missing.jpg")) is None
    assert _file_sha16(None) is None


def test_create_and_run_stamps_input_provenance(tmp_path):
    """上传研判后信封必须带输入文件 hash（审计§八 provenance）。"""
    from fastapi.testclient import TestClient

    from backend.app.main import app

    image = tmp_path / "probe.jpg"
    import hashlib
    payload = b"\xff\xd8\xff\xe0" + b"\x00" * 128
    image.write_bytes(payload)
    expected = hashlib.sha256(payload).hexdigest()[:16]

    with TestClient(app) as client:
        response = client.post(
            "/api/analyze/upload",
            files={"file": ("probe.jpg", payload, "image/jpeg")},
            data={"use_vlm": "false", "environment_mode": "offline"},
            timeout=300,
        )
    assert response.status_code == 200
    envelope = response.json()
    provenance = (envelope.get("result") or {}).get("input_provenance") or {}
    assert provenance.get("image_sha256_16") == expected
    assert provenance.get("image_name") == "probe.jpg"
    # 清理：测试任务立即终止释放资源锁
    aid = envelope.get("analysis_id")
    client.post(f"/api/tasks/{aid}/approval", json={"action": "terminate", "reason": "测试清理"})


# ---------- 架构纪要对照（docs/架构职责划分纪要.md） ----------

def test_fire_metrics_reports_image_ratio():
    """纪要§二：PWM-YOLO 输出火焰/烟雾在图像中的占比。"""
    from backend.app.tools.core import calculate_fire_metrics

    metrics = calculate_fire_metrics(
        [{"class_name": "fire", "box": [0, 0, 10, 10]},
         {"class_name": "smoke", "box": [0, 0, 20, 10]}],
        image_width=100, image_height=100,
    )
    assert metrics["fire_ratio"] == 0.01
    assert metrics["smoke_ratio"] == 0.02


def test_environment_surfaces_temperature_humidity_precipitation():
    """纪要§四：地理环境信息模块向决策层提供温度、湿度、降水。"""
    from backend.app.tools.environment import EnvironmentTool

    raw = {"status": "ok",
           "weather": {"status": "ok", "temperature_c": 21.5, "relative_humidity_pct": 63.0,
                       "precipitation_mm": 0.0, "wind_speed_m_s": 3.0,
                       "wind_to_direction": "S", "wind_to_deg": 201.0},
           "terrain": {"status": "ok", "elevation_m": 438.0},
           "water": {"status": "error"}, "road": {"status": "error"}, "landcover": {"status": "error"}}
    data = EnvironmentTool._normalize("forest-demo-01", raw, mode="real", source="test")
    assert data["temperature_c"] == 21.5
    assert data["relative_humidity_pct"] == 63.0
    assert data["precipitation_mm"] == 0.0


def test_report_review_block():
    """纪要§九：复盘档案——初始/最终火势、轮次、版本、审批次数与扑灭判定。"""
    from types import SimpleNamespace

    from backend.app.services.analysis_service import AnalysisService

    item = SimpleNamespace(
        rounds=[
            {"before": {"fire_load_flp": 360.0}, "after": {"fire_load_flp": 300.0}},
            {"before": {"fire_load_flp": 300.0}, "after": {"fire_load_flp": 0.0}},
        ],
        plan_versions=[{"plan_version": 1}, {"plan_version": 2}],
        events=[SimpleNamespace(stage="approval"), SimpleNamespace(stage="approval"), SimpleNamespace(stage="dispatch")],
        result={"fire_assessment": {"fire_load_flp": 360.0}},
        status="completed",
    )
    review = AnalysisService._build_review(item)
    assert review["initial_flp"] == 360.0
    assert review["final_flp"] == 0.0
    assert review["flp_delta"] == -360.0
    assert review["extinguished"] is True
    assert review["round_count"] == 2
    assert review["plan_version_count"] == 2
    assert review["approval_event_count"] == 2
    assert review["status"] == "completed"
