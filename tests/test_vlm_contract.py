"""VLM 视觉分析层测试（docs/VLM队员执行手册.md · 追踪清单 E-2 开发侧就绪）。

覆盖：vlm-analysis-v1 契约校验与禁项守卫、glm 直连客户端的 JSON 修复重试、
analyze_with_vlm 三级来源回退、project-status 接入状态上报。
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.tools.core import analyze_with_vlm  # noqa: E402
from backend.app.vlm import ImageUnreadable, validate_vlm_analysis, vlm_analyze_images  # noqa: E402
from backend.app.vlm import client as vlm_client  # noqa: E402
from backend.app.vlm.contract import SCHEMA_VERSION  # noqa: E402


def _v1_payload(**overrides) -> dict:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "task_id": "task-1",
        "round_index": 1,
        "mode": "model",
        "source": "glm-4.6v-flash",
        "usable": True,
        "quality_level": "clear",
        "problems": [],
        "missing_inputs": [],
        "fire_presence": "observed",
        "smoke_density": "moderate",
        "image_plane_drift": "left-up",
        "temporal_trend": "intensifying",
        "people": {"state": "not_observed"},
        "scene_elements": {"water": {"state": "water_candidate"}},
        "human_summary": "画面中可见明火与烟雾，未观察到人员。",
    }
    payload.update(overrides)
    return payload


# ---------- contract.validate_vlm_analysis ----------

def test_valid_payload_passes_unchanged():
    cleaned, report = validate_vlm_analysis(_v1_payload(), task_id="task-1", round_index=1)
    assert report["valid"] is True
    assert report["violations"] == []
    assert cleaned["human_summary"].startswith("画面中可见明火")


def test_wrong_schema_version_is_rejected_wholesale():
    cleaned, report = validate_vlm_analysis(_v1_payload(schema_version="vlm-analysis-v2"))
    assert cleaned is None
    assert not report["valid"]


def test_identity_echo_mismatch_is_rejected():
    cleaned, report = validate_vlm_analysis(_v1_payload(task_id="other-task"), task_id="task-1")
    assert cleaned is None
    assert "task_id" in report["missing_fields"][0]


def test_round_index_string_echo_is_normalized():
    cleaned, report = validate_vlm_analysis(_v1_payload(round_index="1"), round_index=1)
    assert report["valid"] is True
    cleaned, _ = validate_vlm_analysis(_v1_payload(round_index=2), round_index=1)
    assert cleaned is None


def test_forbidden_rule_numbers_are_stripped():
    payload = _v1_payload(flp=245.7, wind_speed=3.4, drone_count=3,
                          nested={"control_time": 12, "keep": 1})
    cleaned, report = validate_vlm_analysis(payload)
    assert report["valid"] and report["violations"]
    assert "flp" not in cleaned and "wind_speed" not in cleaned and "drone_count" not in cleaned
    assert cleaned["nested"] == {"keep": 1}
    # 剥除越界后要求人工复核
    assert cleaned["manual_review_required"] is True


def test_people_absent_is_coerced_to_not_observed():
    cleaned, report = validate_vlm_analysis(_v1_payload(people={"state": "absent"}))
    assert cleaned["people"]["state"] == "not_observed"
    assert any("not_observed" in violation for violation in report["violations"])


def test_water_confirmed_is_clamped_to_candidate():
    payload = _v1_payload(scene_elements={"water": {"state": "confirmed"}})
    cleaned, report = validate_vlm_analysis(payload)
    assert cleaned["scene_elements"]["water"]["state"] == "water_candidate"
    assert any("water_candidate" in violation for violation in report["violations"])


# ---------- client.vlm_analyze_images ----------

class _FakeResponse:
    def __init__(self, content: str):
        self._content = content

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


@pytest.fixture
def vlm_env(monkeypatch):
    monkeypatch.setenv("FIRE_VLM_API_KEY", "test-key")
    monkeypatch.setattr(vlm_client, "_FAILURES", 0)


def _write_png(tmp_path: Path, name: str = "frame.jpg") -> str:
    path = tmp_path / name
    path.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg-bytes")
    return str(path)


def test_client_parses_valid_json_first_try(tmp_path, vlm_env, monkeypatch):
    calls = []

    def fake_post(url, **kwargs):
        calls.append(kwargs.get("json"))
        return _FakeResponse(json.dumps(_v1_payload(), ensure_ascii=False))

    monkeypatch.setattr(vlm_client.requests, "post", fake_post)
    result = vlm_analyze_images([_write_png(tmp_path)], observation={}, environment={},
                                people_status="unknown", task_id="task-1", round_index=1)
    assert result["schema_version"] == SCHEMA_VERSION
    assert len(calls) == 1
    # 视觉消息：system + user(图片部件+文本)
    assert calls[0]["messages"][0]["role"] == "system"
    user_parts = calls[0]["messages"][1]["content"]
    assert user_parts[0]["type"] == "image_url"
    assert user_parts[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_client_retries_once_on_invalid_json(tmp_path, vlm_env, monkeypatch):
    responses = [_FakeResponse("抱歉，我无法输出 JSON。"), _FakeResponse(json.dumps(_v1_payload()))]

    def fake_post(url, **kwargs):
        return responses.pop(0)

    monkeypatch.setattr(vlm_client.requests, "post", fake_post)
    result = vlm_analyze_images([_write_png(tmp_path)], observation={}, environment={})
    assert result["schema_version"] == SCHEMA_VERSION
    assert not responses  # 恰好用满一次修复重试


def test_client_returns_none_after_second_invalid_json(tmp_path, vlm_env, monkeypatch):
    def fake_post(url, **kwargs):
        return _FakeResponse("仍然不是 JSON")

    monkeypatch.setattr(vlm_client.requests, "post", fake_post)
    assert vlm_analyze_images([_write_png(tmp_path)], observation={}, environment={}) is None


def test_client_raises_image_unreadable_without_calling_api(tmp_path, vlm_env, monkeypatch):
    def fail_post(url, json=None, headers=None, timeout=None):
        raise AssertionError("不可读图片不应发起网络调用")

    monkeypatch.setattr(vlm_client.requests, "post", fail_post)
    with pytest.raises(ImageUnreadable):
        vlm_analyze_images([str(tmp_path / "missing.jpg")], observation={}, environment={})


def test_client_caps_sequence_at_four_images(tmp_path, vlm_env, monkeypatch):
    capture = {}

    def fake_post(url, **kwargs):
        capture["json"] = kwargs.get("json")
        return _FakeResponse("{}")

    monkeypatch.setattr(vlm_client.requests, "post", fake_post)
    paths = [_write_png(tmp_path, f"f{i}.jpg") for i in range(6)]
    vlm_analyze_images(paths, observation={}, environment={})
    image_parts = [part for part in capture["json"]["messages"][1]["content"] if part.get("type") == "image_url"]
    assert len(image_parts) == 4


def test_client_degraded_after_two_failures_skips_network(tmp_path, vlm_env, monkeypatch):
    def fail_post(url, **kwargs):
        raise OSError("network down")

    monkeypatch.setattr(vlm_client.requests, "post", fail_post)
    assert vlm_analyze_images([_write_png(tmp_path)], observation={}, environment={}) is None
    assert vlm_analyze_images([_write_png(tmp_path)], observation={}, environment={}) is None
    assert vlm_client._FAILURES >= 2
    # 第 3 次调用 degraded 门控直接 None，不再发起网络调用
    def boom_post(url, **kwargs):
        raise AssertionError("degraded 状态不应发起网络调用")

    monkeypatch.setattr(vlm_client.requests, "post", boom_post)
    assert vlm_analyze_images([_write_png(tmp_path)], observation={}, environment={}) is None
    assert not vlm_client.vlm_client_status()["available"]
    assert vlm_client.vlm_client_status()["mode"] == "deterministic-offline"


# ---------- tools.analyze_with_vlm 三级来源 ----------

def test_analyze_with_vlm_falls_back_to_rule_explainer_without_config(monkeypatch):
    monkeypatch.delenv("FIRE_VLM_ENDPOINT", raising=False)
    monkeypatch.delenv("FIRE_VLM_API_KEY", raising=False)
    result = analyze_with_vlm(observation={"detections": []}, people_status="unknown")
    assert result["mode"] == "fallback"
    assert result["source"] == "rule-explainer-fallback"


def test_analyze_with_vlm_direct_path_returns_contract_payload(tmp_path, vlm_env, monkeypatch):
    monkeypatch.delenv("FIRE_VLM_ENDPOINT", raising=False)

    def fake_post(url, **kwargs):
        return _FakeResponse(json.dumps(_v1_payload(), ensure_ascii=False))

    monkeypatch.setattr(vlm_client.requests, "post", fake_post)
    result = analyze_with_vlm(
        observation={"detections": []}, people_status="unknown",
        image_paths=[_write_png(tmp_path)], task_id="task-1", round_index=1,
    )
    assert result["mode"] == "real"
    assert result["source"] == "vlm-glm-4.6v-flash"
    assert result["prompt_version"] == "v1"
    assert result["schema_version"] == SCHEMA_VERSION
    # 下游合并沿用 summary 字段（human_summary 镜像）
    assert result["summary"] == "画面中可见明火与烟雾，未观察到人员。"


def test_analyze_with_vlm_call_failure_falls_back_with_code(tmp_path, monkeypatch):
    monkeypatch.delenv("FIRE_VLM_ENDPOINT", raising=False)
    monkeypatch.setenv("FIRE_VLM_API_KEY", "test-key")

    def fail_post(url, **kwargs):
        raise OSError("network down")

    monkeypatch.setattr(vlm_client.requests, "post", fail_post)
    result = analyze_with_vlm(observation={"detections": []}, people_status="unknown",
                              image_paths=[_write_png(tmp_path)])
    assert result["mode"] == "fallback"
    assert result["adapter_fallback"]["code"] == "vlm_call_failed"


def test_analyze_with_vlm_strict_real_returns_structured_error(tmp_path, vlm_env, monkeypatch):
    monkeypatch.delenv("FIRE_VLM_ENDPOINT", raising=False)

    def fail_post(url, **kwargs):
        raise OSError("network down")

    monkeypatch.setattr(vlm_client.requests, "post", fail_post)
    result = analyze_with_vlm(observation={"detections": []}, people_status="unknown",
                              image_paths=[_write_png(tmp_path)], strict_real=True)
    assert result["status"] == "error"
    assert result["error"]["code"] == "vlm_unavailable"


def test_analyze_with_vlm_contract_invalid_falls_back(tmp_path, vlm_env, monkeypatch):
    monkeypatch.delenv("FIRE_VLM_ENDPOINT", raising=False)

    def fake_post(url, **kwargs):
        return _FakeResponse('{"note": "不是 vlm-analysis-v1"}')

    monkeypatch.setattr(vlm_client.requests, "post", fake_post)
    result = analyze_with_vlm(observation={"detections": []}, people_status="unknown",
                              image_paths=[_write_png(tmp_path)])
    assert result["mode"] == "fallback"
    assert result["adapter_fallback"]["code"] == "vlm_contract_invalid"


# ---------- project-status 接入状态 ----------

def test_project_status_reports_env_based_adapters(monkeypatch):
    from fastapi.testclient import TestClient

    from backend.app.main import app

    monkeypatch.setenv("FIRE_VLM_API_KEY", "test-key")
    monkeypatch.delenv("FIRE_YOLO_ENDPOINT", raising=False)
    with TestClient(app) as client:
        response = client.get("/api/project-status")
    assert response.status_code == 200
    body = response.json()
    assert body["vlm"] == "configured"
    assert body["yolo"] == "pending"
