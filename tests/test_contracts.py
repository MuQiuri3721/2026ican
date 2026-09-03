import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.main import app  # noqa: E402
from backend.app.tools.registry import build_registry  # noqa: E402
from backend.app.tools.environment import EnvironmentTool  # noqa: E402
from backend.app.domain.schemas import UAVRecord, InventorySnapshot  # noqa: E402
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


def test_analysis_requires_approval_before_monitoring_and_rounds():
    client = TestClient(app)
    response = client.post("/api/analyze", json={"scene_id": "forest-demo-01", "image_name": "demo.jpg"})
    assert response.status_code == 200
    payload = response.json()
    analysis_id = payload["analysis_id"]
    assert payload["status"] == "awaiting_confirmation"
    assert client.get("/api/analyze/" + analysis_id).status_code == 200

    monitor = client.post("/api/monitor/" + analysis_id, json={"elapsed_minutes": 5, "extinguishing_liters": 40})
    assert monitor.status_code == 409
    round_response = client.post(f"/api/tasks/{analysis_id}/rounds", json={"round": 1})
    assert round_response.status_code == 409

    plan = client.get(f"/api/tasks/{analysis_id}/plan").json()["plan"]
    approved = client.post(
        f"/api/tasks/{analysis_id}/approval",
        json={"action": "approve", "plan_id": plan["plan_id"], "idempotency_key": "approve-once"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "executing"

    monitor = client.post("/api/monitor/" + analysis_id, json={"elapsed_minutes": 5, "extinguishing_liters": 40})
    assert monitor.status_code == 200
    assert monitor.json()["action"] in {"continue", "resupply", "reinforce", "return", "finish"}
    assert client.post(f"/api/tasks/{analysis_id}/approval", json={"action": "terminate"}).status_code == 200


def test_fleet_and_inventory_contract_are_2_plus_4_plus_2_and_non_negative():
    client = TestClient(app)
    fleet_response = client.get("/api/fleet")
    assert fleet_response.status_code == 200
    fleet = fleet_response.json()
    assert fleet["schema_version"] == "fleet-v1"
    assert fleet["count"] == 8
    assert {uav["subgroup"] for uav in fleet["fleet"]} == {"reconnaissance", "suppression", "support"}
    assert sum(uav["subgroup"] == "reconnaissance" for uav in fleet["fleet"]) == 2
    assert sum(uav["subgroup"] == "suppression" for uav in fleet["fleet"]) == 4
    assert sum(uav["subgroup"] == "support" for uav in fleet["fleet"]) == 2
    assert all(0 <= uav["soc"] <= 100 and uav["agent_remaining"] >= 0 for uav in fleet["fleet"])

    inventory_response = client.get("/api/inventory")
    assert inventory_response.status_code == 200
    inventory = inventory_response.json()
    assert inventory["schema_version"] == "inventory-v1"
    for key, value in inventory.items():
        if key.endswith("_liters") or key.endswith("_kg") or key.endswith("_packs") or key.startswith(("water_modules", "co2_modules", "support_boxes")):
            assert value >= 0


def _create_offline_task(client: TestClient) -> tuple[str, dict]:
    response = client.post("/api/analyze", json={
        "scene_id": "forest-demo-01",
        "image_name": "offline.jpg",
        "environment_mode": "offline",
    })
    assert response.status_code == 200, response.text
    task = response.json()
    assert task["status"] == "awaiting_confirmation"
    plan_response = client.get(f"/api/tasks/{task['analysis_id']}/plan")
    assert plan_response.status_code == 200
    return task["analysis_id"], plan_response.json()["plan"]


def test_offline_task_plan_approval_round_and_report_contract():
    client = TestClient(app)
    task_id, plan = _create_offline_task(client)
    assert plan["task_id"] == task_id
    assert plan["schema_version"] == "uav-dispatch-v1"
    assert plan["required_drones"] >= 1
    assert isinstance(plan["tasks"], list)

    approved = client.post(f"/api/tasks/{task_id}/approval", json={"action": "approve", "plan_id": plan["plan_id"]})
    assert approved.status_code == 200
    approved_payload = approved.json()
    assert approved_payload["status"] == "executing"
    assert approved_payload["approval"]["action"] == "approve"
    assert approved_payload["resource_locks"]

    round_one = client.post(f"/api/tasks/{task_id}/rounds", json={
        "round": 1, "fire_load_flp": 60, "growth_rate": 0.1,
        "wind_speed": 5, "people_status": "absent", "elapsed_minutes": 5,
        "extinguishing_liters": 20,
    })
    round_payload = round_one.json()
    assert round_payload["round"] == 1
    assert {"before", "after", "changes", "next_action"}.issubset(round_payload)
    assert round_payload["before"]["fleet"]
    assert round_payload["after"]["fleet"]
    assert round_payload["changes"]["action"]
    assert round_payload["next_action"] in {"awaiting_confirmation", "continue", "resupply", "reinforce", "return", "finish"}

    report = client.get(f"/api/tasks/{task_id}/report")
    assert report.status_code == 200
    assert report.json()["task_id"] == task_id
    assert len(report.json()["plan_versions"]) >= 1
    assert len(report.json()["rounds"]) == 1
    assert report.json()["events"]


def test_task_state_machine_adjust_replan_idempotency_and_terminal_operations():
    client = TestClient(app)
    task_id, plan = _create_offline_task(client)

    # Stale plans and execution before approval are rejected.
    stale = client.post(f"/api/tasks/{task_id}/approval", json={"action": "approve", "plan_id": "plan-stale"})
    assert stale.status_code == 409
    assert client.post(f"/api/tasks/{task_id}/replan", json={"triggers": ["manual"]}).status_code == 200
    replacement = client.get(f"/api/tasks/{task_id}/plan").json()["plan"]
    assert replacement["plan_id"] != plan["plan_id"]
    assert replacement["plan_version"] == plan.get("plan_version", 1) + 1
    assert client.get(f"/api/analyze/{task_id}").json()["resource_locks"] == []

    approval_body = {"action": "approve", "plan_id": replacement["plan_id"], "idempotency_key": "approve-1"}
    approved = client.post(f"/api/tasks/{task_id}/approval", json=approval_body)
    assert approved.status_code == 200
    assert approved.json()["status"] == "executing"
    repeated = client.post(f"/api/tasks/{task_id}/approval", json=approval_body)
    assert repeated.status_code == 200
    assert repeated.json()["status"] == "executing"
    assert repeated.json()["resource_locks"] == approved.json()["resource_locks"]

    adjusted = client.post(
        f"/api/tasks/{task_id}/approval",
        json={"action": "adjust", "constraints": {"max_rounds": 3}, "idempotency_key": "adjust-1"},
    )
    assert adjusted.status_code == 200
    assert adjusted.json()["plan"]["plan_version"] == replacement["plan_version"] + 1
    assert adjusted.json()["plan"]["plan_id"] != replacement["plan_id"]
    assert adjusted.json()["versions"][-1]["plan_id"] == adjusted.json()["plan"]["plan_id"]
    assert client.get(f"/api/analyze/{task_id}").json()["resource_locks"] == []

    new_plan = adjusted.json()["plan"]
    assert client.post(f"/api/tasks/{task_id}/approval", json={"action": "approve", "plan_id": new_plan["plan_id"]}).status_code == 200
    duplicate_round = client.post(f"/api/tasks/{task_id}/rounds", json={"round": 1, "extinguishing_liters": 0})
    assert duplicate_round.status_code == 200
    duplicate_round_again = client.post(f"/api/tasks/{task_id}/rounds", json={"round": 1, "extinguishing_liters": 0})
    assert duplicate_round_again.status_code == 409

    terminated = client.post(f"/api/tasks/{task_id}/approval", json={"action": "terminate", "reason": "合同测试"})
    assert terminated.status_code == 200
    assert terminated.json()["status"] == "terminated"
    assert terminated.json()["resource_locks"] == []
    assert client.post(f"/api/tasks/{task_id}/rounds", json={"round": 2}).status_code == 409
    assert client.post(f"/api/tasks/{task_id}/approval", json={"action": "approve"}).status_code == 409
    assert client.post(f"/api/tasks/{task_id}/approval", json={"action": "adjust"}).status_code == 409
    assert client.post(f"/api/tasks/{task_id}/replan", json={"triggers": ["wind_band_changed"]}).status_code == 409
    assert client.post(f"/api/monitor/{task_id}", json={"elapsed_minutes": 5}).status_code == 409


def test_domain_contract_rejects_invalid_payload_and_negative_inventory():
    with pytest.raises(ValueError):
        UAVRecord(uav_id="E-test", subgroup="suppression", soc=50, payload_capacity_kg=25,
                  payload_module="water_20l", agent_remaining=1, agent_unit="kg", speed_mps=8,
                  energy_rate_percent_per_hour=100)
    with pytest.raises(ValueError):
        InventorySnapshot(water_liters=-1)
