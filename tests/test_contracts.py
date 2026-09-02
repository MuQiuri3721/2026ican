import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.main import app  # noqa: E402
from backend.app.tools.registry import build_registry  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def test_registry_contains_core_tools():
    tools = build_registry().list()
    assert len(tools) >= 29
    assert {"detect_fire", "calculate_resource_need", "make_next_decision"}.issubset(tools)


def test_unknown_scene_returns_tool_error():
    result = build_registry().execute("get_environment", {"scene_id": "unknown"})
    assert result["ok"] is False
    assert result["error"]["code"] == "scene_not_found"


def test_analysis_can_be_retrieved_and_monitored():
    client = TestClient(app)
    response = client.post("/api/analyze", json={"scene_id": "forest-demo-01", "image_name": "demo.jpg"})
    assert response.status_code == 200
    payload = response.json()
    analysis_id = payload["analysis_id"]
    assert client.get("/api/analyze/" + analysis_id).status_code == 200
    monitor = client.post("/api/monitor/" + analysis_id, json={"elapsed_minutes": 5, "extinguishing_liters": 40})
    assert monitor.status_code == 200
    assert monitor.json()["action"] in {"continue", "resupply", "reinforce", "return", "finish"}
