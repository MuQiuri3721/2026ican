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
    """交付 v4 §二的嵌套结构（48 次实测的真实形状）。"""
    payload = {
        "schema_version": SCHEMA_VERSION,
        "task_id": "task-1",
        "round_index": 1,
        "image_ids": ["F1"],
        "mode": "model",
        "source": "glm-4.6v-flash",
        "image_quality": {"usable": True, "quality_level": "good", "problems": ["none"], "missing_inputs": []},
        "fire_observation": {"fire_presence": "flame_observed", "affected_layer": "surface",
                             "canopy_involvement": "not_observed", "visual_scale": "medium"},
        "smoke_trend": {"smoke_density": "heavy", "image_plane_drift": "left-up",
                        "temporal_trend": "intensifying"},
        "object_clues": {"people": {"state": "not_observed", "evidence": ""}},
        "review": {"conflicts": [], "manual_review_required": False,
                   "human_summary": "画面中可见明火与烟雾，未观察到人员。"},
    }
    payload.update(overrides)
    return payload


# ---------- contract.validate_vlm_analysis ----------

def test_valid_payload_passes_unchanged():
    cleaned, report = validate_vlm_analysis(_v1_payload(), task_id="task-1", round_index=1)
    assert report["valid"] is True
    assert report["violations"] == []
    assert cleaned["review"]["human_summary"].startswith("画面中可见明火")


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


def test_object_clues_people_absent_is_clamped():
    """交付实测结构（prompt-v4 §二）：对象线索挂在 object_clues 下，钳位必须同样生效。"""
    payload = _v1_payload(object_clues={"people": {"state": "absent", "evidence": ""},
                                        "water": {"state": "confirmed", "evidence": "河面"}})
    cleaned, report = validate_vlm_analysis(payload)
    assert cleaned["object_clues"]["people"]["state"] == "not_observed"
    assert cleaned["object_clues"]["water"]["state"] == "water_candidate"
    assert len(report["violations"]) == 2
    assert cleaned["manual_review_required"] is True


def test_fenced_output_is_parsed_after_fence_strip(vlm_env, tmp_path, monkeypatch):
    """交付 P01：v1 下 12/12 次输出被 ``` 围栏包裹；解析必须取首 { 至末 } 剥围栏。"""
    fenced = "```json\n" + json.dumps(_v1_payload(), ensure_ascii=False) + "\n```"

    def fake_post(url, **kwargs):
        return _FakeResponse(fenced)

    monkeypatch.setattr(vlm_client.requests, "post", fake_post)
    result = vlm_analyze_images([_write_png(tmp_path)], observation={}, environment={},
                                task_id="task-1", round_index=1)
    assert result is not None
    assert result["schema_version"] == SCHEMA_VERSION


def test_empty_http_200_counts_as_failure(vlm_env, tmp_path, monkeypatch):
    """交付 P07：HTTP 200 空响应按可重试失败处理，不得重置失败计数。"""

    def fake_post(url, **kwargs):
        return _FakeResponse("")

    monkeypatch.setattr(vlm_client.requests, "post", fake_post)
    assert vlm_analyze_images([_write_png(tmp_path)], observation={}, environment={}) is None
    assert vlm_client._FAILURES == 1


def test_user_message_carries_task_info_and_multi_image_note(vlm_env, tmp_path, monkeypatch):
    """交付 v1.1/v4：用户消息首行「任务信息」携带 task_id；多图轮次注入帧序列说明行。"""
    capture = {}

    def fake_post(url, **kwargs):
        capture["json"] = kwargs.get("json")
        return _FakeResponse(json.dumps(_v1_payload()))

    monkeypatch.setattr(vlm_client.requests, "post", fake_post)
    paths = [_write_png(tmp_path, "f1.jpg"), _write_png(tmp_path, "f2.jpg")]
    vlm_analyze_images(paths, observation={}, environment={}, task_id="task-9", round_index=2)
    text_parts = [part["text"] for part in capture["json"]["messages"][1]["content"] if part.get("type") == "text"]
    assert "任务信息：task_id=task-9, round_index=2" in text_parts[0]
    assert "帧序列" in text_parts[0]  # 多图 → 说明行存在
    assert capture["json"]["max_tokens"] == 2048 and capture["json"]["temperature"] == 0.1
    assert "vlm-analysis-v1 输出结构定义" in capture["json"]["messages"][0]["content"]


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


def test_client_repairs_incomplete_payload_once(tmp_path, vlm_env, monkeypatch):
    """交付 §7-1：解析成功但缺必填字段组（P01/P02 残留）→ 带缺失清单定向修复一次。"""
    incomplete = {"schema_version": SCHEMA_VERSION, "task_id": "task-1", "round_index": 1,
                  "fire_presence": "flame_observed"}
    calls = []

    def fake_post(url, **kwargs):
        calls.append(kwargs.get("json"))
        if len(calls) == 1:
            return _FakeResponse(json.dumps(incomplete))
        assert "image_quality" in kwargs["json"]["messages"][-1]["content"]  # 缺失清单已回传
        return _FakeResponse(json.dumps(_v1_payload()))

    monkeypatch.setattr(vlm_client.requests, "post", fake_post)
    result = vlm_analyze_images([_write_png(tmp_path)], observation={}, environment={})
    assert len(calls) == 2
    assert "image_quality" in result and result["review"]["human_summary"]


def test_analyze_with_vlm_sparse_payload_falls_back_as_contract_invalid(tmp_path, vlm_env, monkeypatch):
    """修复后仍缺字段组：客户端原样上交，契约层按"缺少必填字段组"整包作废 → vlm_contract_invalid。"""
    monkeypatch.delenv("FIRE_VLM_ENDPOINT", raising=False)
    sparse = {"schema_version": SCHEMA_VERSION, "task_id": "task-1", "round_index": 1}

    def fake_post(url, **kwargs):
        return _FakeResponse(json.dumps(sparse))

    monkeypatch.setattr(vlm_client.requests, "post", fake_post)
    result = analyze_with_vlm(
        observation={"detections": []}, people_status="unknown",
        image_paths=[_write_png(tmp_path)], task_id="task-1", round_index=1,
    )
    assert result["mode"] == "fallback"
    assert result["adapter_fallback"]["code"] == "vlm_contract_invalid"


def test_contract_rejects_missing_required_groups():
    """契约 §10.2：五组必填字段组缺一即整包作废（交付 prompt-v4 §二：所有字段必须全部出现）。"""
    cleaned, report = validate_vlm_analysis({"schema_version": SCHEMA_VERSION, "task_id": "t", "round_index": 1})
    assert cleaned is None
    assert "缺少必填字段组" in report["missing_fields"][0]


def test_client_completes_truncated_then_repaired_payload(tmp_path, vlm_env, monkeypatch):
    """截断载荷走格式修复后仍缺组 → 必须再走缺字段定向修复（原漏洞：格式修复路径绕过完整性检查）。"""
    truncated = json.dumps(_v1_payload())[:80]  # 截断 → 非法 JSON
    calls = []

    def fake_post(url, **kwargs):
        calls.append(kwargs.get("json"))
        if len(calls) == 1:
            return _FakeResponse(truncated)  # 截断 → 非法 JSON
        if len(calls) == 2:
            # 格式修复重试：模型回了只含身份字段的最小 JSON
            return _FakeResponse(json.dumps({"schema_version": SCHEMA_VERSION, "task_id": "task-1", "round_index": 1}))
        return _FakeResponse(json.dumps(_v1_payload()))

    monkeypatch.setattr(vlm_client.requests, "post", fake_post)
    result = vlm_analyze_images([_write_png(tmp_path)], observation={}, environment={})
    assert len(calls) == 3  # 首调 + 格式修复 + 缺字段定向修复
    assert "image_quality" in result


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


def test_client_degraded_gate_recovers_after_cooldown(tmp_path, vlm_env, monkeypatch):
    """BE-11：降级门控冷却结束后放行试探调用，成功即复位（不再永久残废）。"""
    monkeypatch.setattr(vlm_client, "_FAILURES", 2)
    monkeypatch.setattr(vlm_client, "_LAST_FAIL", __import__("time").monotonic() - 301)
    assert vlm_client.vlm_client_status()["mode"] == "deterministic-offline"  # 冷却内仍显示降级

    def fake_post(url, **kwargs):
        return _FakeResponse(json.dumps(_v1_payload()))

    monkeypatch.setattr(vlm_client.requests, "post", fake_post)
    result = vlm_analyze_images([_write_png(tmp_path)], observation={}, environment={})
    assert result is not None  # 冷却结束放行试探
    assert vlm_client._FAILURES == 0  # 成功复位
    assert vlm_client.vlm_client_status()["mode"] == "glm-vision"


# ---------- tools.analyze_with_vlm 三级来源 ----------

def test_analyze_with_vlm_adapter_tier_applies_contract_and_flatten(monkeypatch):
    """交付契约形态（vlm-analysis-v1）的适配器响应同样过守卫+展平（api-contract §10.1）。"""
    nested = {
        "schema_version": SCHEMA_VERSION,
        "task_id": "task-adapter",
        "round_index": 1,
        "image_quality": {"usable": True, "quality_level": "good", "problems": ["none"], "missing_inputs": []},
        "fire_observation": {"fire_presence": "smoke_only", "affected_layer": "surface",
                             "canopy_involvement": "not_observed", "visual_scale": "medium"},
        "smoke_trend": {"smoke_density": "light", "image_plane_drift": "uncertain",
                        "temporal_trend": "first_round_no_comparison"},
        "object_clues": {"people": {"state": "not_observed", "evidence": ""}},
        "review": {"conflicts": [], "manual_review_required": False, "human_summary": "画面只有薄烟，无明火。"},
    }

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(nested).encode()

    monkeypatch.setenv("FIRE_VLM_ENDPOINT", "http://127.0.0.1:9/vlm")
    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout=None: FakeResp())
    result = analyze_with_vlm(observation={"detections": []}, people_status="unknown")
    assert result["mode"] == "real" and result["source"] == "vlm-adapter"
    assert result["fire_presence"] == "smoke_only"
    assert result["usable"] is True
    assert result["summary"] == "画面只有薄烟，无明火。"


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
    assert result["prompt_version"] == "v4"  # 交付包最终版（2026-09-06）
    assert result["schema_version"] == SCHEMA_VERSION
    # 下游合并沿用 summary 字段（human_summary 镜像）
    assert result["summary"] == "画面中可见明火与烟雾，未观察到人员。"


def test_analyze_with_vlm_flattens_delivered_nested_groups(tmp_path, vlm_env, monkeypatch):
    """交付 v4 真实输出为分组嵌套（prompt-v4 §二，48 次实测）；平台展开顶层别名供前端事实行沿用。"""
    monkeypatch.delenv("FIRE_VLM_ENDPOINT", raising=False)
    nested = {
        "schema_version": SCHEMA_VERSION,
        "task_id": "task-1",
        "round_index": 1,
        "image_ids": ["F1"],
        "prompt_version": "v4",
        "image_quality": {"usable": False, "quality_level": "poor", "problems": ["too_dark"], "missing_inputs": ["PWM-YOLO结果"]},
        "fire_observation": {"fire_presence": "smoke_only", "affected_layer": "surface",
                             "canopy_involvement": "not_observed", "visual_scale": "medium"},
        "smoke_trend": {"smoke_density": "heavy", "image_plane_drift": "uncertain",
                        "temporal_trend": "first_round_no_comparison"},
        "object_clues": {"people": {"state": "not_observed", "evidence": ""},
                         "water": {"state": "water_candidate", "evidence": ""}},
        "review": {"conflicts": ["YOLO 标注火焰但画面不可见"], "manual_review_required": True,
                   "human_summary": "画面只见烟雾，未见明火。"},
    }

    def fake_post(url, **kwargs):
        return _FakeResponse(json.dumps(nested, ensure_ascii=False))

    monkeypatch.setattr(vlm_client.requests, "post", fake_post)
    result = analyze_with_vlm(
        observation={"detections": []}, people_status="unknown",
        image_paths=[_write_png(tmp_path)], task_id="task-1", round_index=1,
    )
    # 顶层别名展开（前端 vlmNoteFacts/vlmNoteIssues 读扁平键）
    assert result["usable"] is False and result["quality_level"] == "poor"
    assert result["fire_presence"] == "smoke_only"
    assert result["smoke_density"] == "heavy" and result["temporal_trend"] == "first_round_no_comparison"
    assert result["people"] == {"state": "not_observed", "evidence": ""}
    assert result["conflicts"] == ["YOLO 标注火焰但画面不可见"]
    assert result["summary"] == "画面只见烟雾，未见明火。"
    # 嵌套原件保留可追溯
    assert result["fire_observation"]["fire_presence"] == "smoke_only"
    assert result["review"]["manual_review_required"] is True


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
