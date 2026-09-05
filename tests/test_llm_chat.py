"""LLM 解释层契约（api-contract §5.11/§5.12）：llm-status 形状、chat 降级与数字审计。

测试强制离线路径（patch agentkit.llm._api_key），不依赖外部 GLM Key。
"""
from fastapi.testclient import TestClient

from backend.app.agentkit import llm as agentkit_llm
from backend.app.main import app
from backend.app.routes import assistant_routes


def _client() -> TestClient:
    return TestClient(app)


def _force_offline(monkeypatch):
    monkeypatch.setattr(agentkit_llm, "_api_key", lambda: "")
    monkeypatch.setattr(assistant_routes, "llm_available", lambda: False)


def test_llm_status_shape_offline(monkeypatch):
    _force_offline(monkeypatch)
    payload = _client().get("/api/llm-status").json()
    assert payload["connected"] is False
    assert payload["configured"] is False
    assert payload["model"] is None
    assert payload["degraded"] is False
    assert payload["mode"] == "deterministic-offline"
    assert isinstance(payload["fail_streak"], int)


def test_chat_validation_and_unknown_task(monkeypatch):
    _force_offline(monkeypatch)
    client = _client()
    assert client.post("/api/tasks/does-not-exist/chat", json={"question": "火势如何？"}).status_code == 404
    task_id = _create_offline_task(client)
    assert client.post(f"/api/tasks/{task_id}/chat", json={"question": "   "}).status_code == 400


def test_chat_offline_deterministic_fallback(monkeypatch):
    _force_offline(monkeypatch)
    client = _client()
    task_id = _create_offline_task(client)
    response = client.post(f"/api/tasks/{task_id}/chat", json={"question": "现在火势如何？"})
    assert response.status_code == 200
    payload = response.json()
    assert "阶段" in payload["answer"]
    assert payload["llm"]["connected"] is False
    assert "⚠" not in payload["answer"]


def test_audit_numbers_marks_unknown_digits():
    brief = "阶段: awaiting_confirmation; FLP 360, 面积 1800m²"
    assert agentkit_llm.audit_numbers("当前 FLP 360,预计 42 分钟完成。", brief) == "当前 FLP 360,预计 42⚠ 分钟完成。"
    assert agentkit_llm.audit_numbers("当前 FLP 360。", brief) == "当前 FLP 360。"


def _create_offline_task(client: TestClient) -> str:
    response = client.post("/api/analyze", json={
        "scene_id": "forest-demo-01",
        "image_name": "offline.jpg",
        "environment_mode": "offline",
    })
    assert response.status_code == 200, response.text
    return response.json()["analysis_id"]
