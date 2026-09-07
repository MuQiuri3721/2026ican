"""审计§十 测试缺口补齐：人员变化触发、药剂耗尽触发、OpenCV 缍失降级。

对应 docs/实现差异审计.md §十（闭环/外部适配两组中此前缺测的三项）。
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402


def test_people_status_change_triggers_replan(tmp_path):
    """审计§十 闭环：人员状态变化必须触发 people_status_changed → 重规划 v2 → 回审批门。"""
    from backend.app.main import app

    # 裸 TestClient（不进 lifespan）：lifespan 会预热环境缓存污染后续契约测试的懒加载断言
    client = TestClient(app)
    if True:
        created = client.post("/api/analyze", json={
            "scene_id": "forest-demo-01", "image_name": "probe",
            "scenario": {"fire_origin": {"x": 100, "y": -200}, "fire_area_m2": 2000, "growth_rate": 0.4},
            "people_status": "unknown", "environment_mode": "offline",
        }, timeout=300)
        assert created.status_code == 200
        aid = created.json()["analysis_id"]
        approved = client.post(f"/api/tasks/{aid}/approval",
                               json={"action": "approve", "reason": "人员变化触发测试"}).json()
        assert approved.get("status") in ("executing", "completed", "monitoring")

        round_resp = client.post(f"/api/tasks/{aid}/rounds", json={
            "round": 1, "elapsed_minutes": 5, "extinguishing_liters": 0,
            "people_status": "confirmed",
        }, timeout=300)
        assert round_resp.status_code == 200
        body = round_resp.json()
        triggers = body.get("replan_triggers") or []
        assert "people_status_changed" in triggers, triggers

        envelope = client.get(f"/api/analyze/{aid}").json()
        assert len(envelope.get("plan_versions") or []) >= 2
        assert envelope.get("status") == "awaiting_confirmation"  # v2 回审批门
        client.post(f"/api/tasks/{aid}/approval", json={"action": "terminate", "reason": "测试清理"})


def test_monitor_agent_insufficient_trigger():
    """审计§十 闭环：基地水剂枯竭且无水源时，E 机停滞必须触发 agent_insufficient。"""
    from backend.app.pipeline import simulate_monitor

    # 状态机语义：弹尽的作业机先返航补给；agent_insufficient 见发生在已回基地
    # servicing 且无水可灌（无水源+基地枯竭）时——此时停机充电并触发重规划。
    fleet = [{"uav_id": "E1", "subgroup": "suppression", "role": "firefighting", "status": "servicing",
              "position": {"x": 100, "y": 0}, "soc": 60, "battery": 60,
              "payload_capacity_kg": 25, "payload_module": "water_20l", "payload": 20,
              "agent_remaining": 0, "agent_unit": "L", "speed_mps": 8,
              "energy_rate_percent_per_hour": 270, "signal": 100, "health": 100}]
    inventory = {"water_liters": 0, "water_modules_w20": 0, "co2_modules_c6": 2, "battery_packs": 8,
                 "support_boxes_sup10": 0, "forward_supply_points": [], "water_sources": [],
                 "dry_powder_kg": 0, "nearby_water_available": False}
    analysis = {
        "fire_assessment": {"fire_area_m2": 6000, "growth_rate": 0.1},
        "environment": {"wind_speed": 4.0},
        "dispatch_plan": {"material_module": "water_20l", "fire_load_flp": 60, "growth_flp_per_hour": 24,
                          "selected_uavs": ["E1"], "battery_plan": [{"uav_id": "E1", "outbound_minutes": 0.5}]},
        "fleet": fleet, "inventory": inventory,
    }
    result = simulate_monitor(analysis, elapsed_minutes=5, extinguishing_liters=0,
                              fleet_snapshot=fleet, inventory=inventory)
    assert "agent_insufficient" in (result.get("replan_triggers") or []), result.get("replan_triggers")
    drone = next(d for d in result["next_fleet"] if d["uav_id"] == "E1")
    assert drone["status"] == "charging"  # 无水可灌 → 停机充电等待


def test_extract_video_frames_without_opencv_returns_503(tmp_path, monkeypatch):
    """审计§十 外部适配：OpenCV 缺失时视频处理必须 503 并给出可读提示，不 500。"""
    import sys

    from backend.app.routes.task_routes import _extract_video_frames

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)
    monkeypatch.setitem(sys.modules, "cv2", None)  # import cv2 将抛 ImportError
    with pytest.raises(Exception) as error:
        _extract_video_frames(video)
    assert getattr(error.value, "status_code", None) == 503
    assert "OpenCV" in str(error.value.detail)
