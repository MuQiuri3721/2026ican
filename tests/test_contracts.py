import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.main import app  # noqa: E402
from backend.app.tools.registry import build_registry  # noqa: E402
from backend.app.tools.environment import EnvironmentTool  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def test_environment_demo_has_uniform_contract():
    data = EnvironmentTool().run()
    assert data["mode"] == "demo"
    assert data["source"] == "demo-data"
    assert all(key in data for key in ("wind_speed", "wind_direction", "altitude", "water_sources", "road_context", "landcover", "raw"))


def test_environment_invalid_coordinates_fallback():
    data = EnvironmentTool().run(latitude=100, longitude=10)
    assert data["mode"] == "demo-fallback"
    assert data["fallback"]["code"] == "invalid_coordinates"


def test_environment_real_service_is_lazy_and_normalized(monkeypatch):
    import types
    import sys
    service = types.ModuleType("backend.app.services.environment_service")
    service.get_environment = lambda *args, **kwargs: {
        "status": "partial", "weather": {"status": "ok", "data": {"wind_speed_m_s": 4, "wind_to_direction": "E", "wind_to_deg": 90}},
        "terrain": {"status": "ok", "data": {"elevation_m": 88}}, "water": {"status": "ok", "data": {"nearest": {"distance_m": 12, "name": "河流"}, "preferred": {"distance_m": 30, "name": "水库"}}},
        "road": {"status": "error", "error": "offline"}, "landcover": {"status": "error", "error": "offline"},
    }
    monkeypatch.setitem(sys.modules, "backend.app.services.environment_service", service)
    data = EnvironmentTool().run(latitude=32, longitude=118)
    assert data["mode"] == "real" and data["source"] == "environment_service"
    assert data["wind_speed"] == 4 and data["altitude"] == 88 and "raw" in data


def test_environment_service_failure_fallback(monkeypatch):
    import types
    import sys
    service = types.ModuleType("backend.app.services.environment_service")
    service.get_environment = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline"))
    monkeypatch.setitem(sys.modules, "backend.app.services.environment_service", service)
    data = EnvironmentTool().run(latitude=32, longitude=118)
    assert data["mode"] == "demo-fallback" and data["fallback"]["code"] == "environment_unavailable"


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
