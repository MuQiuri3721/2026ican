"""YOLO/VLM 外部模型适配器的接入协议与回退契约测试。

对应 docs/api-contract.md 第 9、10 节：端点不可用/响应非法时的
strict_real 结构化错误与非 strict_real 的 fixture/规则回退标注。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.tools import core  # noqa: E402
from backend.app.tools.core import analyze_with_vlm, detect_fire  # noqa: E402


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _set_urlopen(monkeypatch, payload: bytes) -> dict:
    recorded = {}

    def fake_urlopen(request, timeout=0):
        recorded["data"] = request.data
        recorded["headers"] = dict(request.header_items())
        return _FakeResponse(payload)

    monkeypatch.setattr(core.urllib.request, "urlopen", fake_urlopen)
    return recorded


def _image_file(tmp_path) -> str:
    target = tmp_path / "frame.jpg"
    target.write_bytes(b"\xff\xd8\xff-fake-jpeg-bytes")
    return str(target)


def test_yolo_endpoint_invalid_payload_falls_back_to_fixture(monkeypatch, tmp_path):
    monkeypatch.setenv("FIRE_YOLO_ENDPOINT", "http://yolo.test/detect")
    _set_urlopen(monkeypatch, json.dumps({"no_detections": True}).encode())
    result = detect_fire(image_name="default", image_path=_image_file(tmp_path))
    assert result["source"] == "vision-observation-fixture"
    assert result["adapter_fallback"]["code"] == "yolo_endpoint_unavailable"


def test_yolo_strict_real_surfaces_structured_error(monkeypatch, tmp_path):
    monkeypatch.setenv("FIRE_YOLO_ENDPOINT", "http://yolo.test/detect")
    _set_urlopen(monkeypatch, b"not-json")
    result = detect_fire(image_name="default", image_path=_image_file(tmp_path), strict_real=True)
    assert result["status"] == "error"
    assert result["error"]["code"] == "detector_unavailable"
    assert result["detections"] == []


def test_yolo_real_detection_payload_accepted(monkeypatch, tmp_path):
    monkeypatch.setenv("FIRE_YOLO_ENDPOINT", "http://yolo.test/detect")
    recorded = _set_urlopen(monkeypatch, json.dumps({
        "detections": [{"class_name": "fire", "confidence": 0.9, "box": [1, 2, 3, 4]}],
        "image_width": 640, "image_height": 480,
    }).encode())
    result = detect_fire(image_name="default", image_path=_image_file(tmp_path))
    assert result["mode"] == "real" and result["source"] == "pwm-yolo-adapter"
    assert result["detections"][0]["class_name"] == "fire"
    assert recorded["headers"].get("Content-type") == "application/octet-stream"


def test_vlm_fallback_without_endpoint(monkeypatch):
    monkeypatch.delenv("FIRE_VLM_ENDPOINT", raising=False)
    result = analyze_with_vlm({"detections": [{"class_name": "fire"}], "fire_area_m2": 100}, {}, "unknown")
    assert result["mode"] == "fallback" and result["source"] == "rule-explainer-fallback"
    assert any("人员" in item for item in result["conflicts"])


def test_vlm_endpoint_unavailable_falls_back(monkeypatch):
    monkeypatch.setenv("FIRE_VLM_ENDPOINT", "http://vlm.test/explain")
    result = analyze_with_vlm({}, {}, "absent")
    assert result["adapter_fallback"]["code"] == "vlm_endpoint_unavailable"


def test_vlm_strict_real_error_and_real_payload_contract(monkeypatch):
    monkeypatch.setenv("FIRE_VLM_ENDPOINT", "http://vlm.test/explain")
    _set_urlopen(monkeypatch, b"not-json")
    strict = analyze_with_vlm({}, {}, "absent", strict_real=True)
    assert strict["status"] == "error" and strict["error"]["code"] == "vlm_unavailable"

    recorded = _set_urlopen(monkeypatch, json.dumps({"summary": "解释"}).encode())
    real = analyze_with_vlm({"fire_area_m2": 1}, {"wind_speed": 3}, "absent")
    assert real["mode"] == "real" and real["source"] == "vlm-adapter"
    assert real["summary"] == "解释"
    body = json.loads(recorded["data"])
    assert set(body) == {"observation", "environment", "people_status"}
