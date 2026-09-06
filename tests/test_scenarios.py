"""六个演示场景的 API 级端到端契约测试。

对应 docs/无人机规则落地实施规划.md 阶段 8 的浏览器六场景：
1. 无人基线（R 监测 + E 灭火 + S 物流）；
2. 确认有人（S 通信/指引分支）；
3. 风速升档触发重规划并生成新方案版本；
4. SOC 不足回返（由 tests/test_rules.py 的 simulate_monitor 低电量算例覆盖：
   API 层任务快照由 Store 持有，无法注入低电量）；
5. 库存不足输出资源缺口（电气火 + C6 库存有限）；
6. 拒绝/调整释放资源并生成新版本。
"""
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.main import app  # noqa: E402


def _client() -> TestClient:
    return TestClient(app)


def _create_task(client: TestClient, **extra) -> dict:
    response = client.post("/api/analyze", json={
        "scene_id": "forest-demo-01", "image_name": "demo.jpg", "environment_mode": "offline", **extra,
    })
    assert response.status_code == 200, response.text
    return response.json()


def _approve(client: TestClient, task_id: str) -> dict:
    plan = client.get(f"/api/tasks/{task_id}/plan").json()["plan"]
    response = client.post(f"/api/tasks/{task_id}/approval", json={"action": "approve", "plan_id": plan["plan_id"]})
    assert response.status_code == 200, response.text
    return response.json()


def _terminate(client: TestClient, task_id: str) -> None:
    response = client.post(f"/api/tasks/{task_id}/approval", json={"action": "terminate", "reason": "场景测试结束"})
    assert response.status_code == 200, response.text


def test_uav_failure_backfill_swaps_roster_inplace():
    """FE-34：场景剧本单机失能 → 规则算两档候选、大脑选人（离线走确定性降级）→ 方案内换机。

    口径：补位不过审批门；失能机置 fault；补位机当轮进入 selected_uavs；
    协作流必须有 UAV_FAULT 与 BACKFILL 两条消息（含轮次幂等标记）。
    """
    client = _client()
    task = _create_task(client, people_status="absent", scenario={
        "fire_origin": {"x": 200, "y": 200}, "fire_area_m2": 900,
        "growth_rate": 0.2, "uav_failure_round": 2,
    })
    task_id = task["analysis_id"]
    _approve(client, task_id)
    first = client.post(f"/api/tasks/{task_id}/rounds", json={"round": 1, "elapsed_minutes": 5, "extinguishing_liters": 100})
    assert first.status_code == 200, first.text
    plan_before = client.get(f"/api/tasks/{task_id}/plan").json()["plan"]
    second = client.post(f"/api/tasks/{task_id}/rounds", json={"round": 2, "elapsed_minutes": 5, "extinguishing_liters": 100})
    assert second.status_code == 200, second.text

    messages = client.get(f"/api/tasks/{task_id}/agent-messages").json()["items"]
    types = [m["msg_type"] for m in messages]
    assert "UAV_FAULT" in types, f"缺少失能消息：{types}"
    assert "BACKFILL" in types, f"缺少补位消息：{types}"
    fault = next(m for m in messages if m["msg_type"] == "UAV_FAULT")
    assert (fault.get("data") or {}).get("round") == 2

    roster_after = set(client.get(f"/api/tasks/{task_id}/plan").json()["plan"]["selected_uavs"])
    faulted = (fault.get("data") or {}).get("faulted")
    backfill_msg = next(m for m in messages if m["msg_type"] == "BACKFILL")
    choice = (backfill_msg.get("data") or {}).get("choice")
    if choice and choice != "none":
        assert choice in roster_after and faulted not in roster_after, "补位机必须换入名单且失能机移出"
    # 幂等：同轮重复上报不得二次注入
    again = client.post(f"/api/tasks/{task_id}/rounds", json={"round": 3, "elapsed_minutes": 5, "extinguishing_liters": 100})
    assert again.status_code == 200
    messages_again = client.get(f"/api/tasks/{task_id}/agent-messages").json()["items"]
    assert sum(1 for m in messages_again if m["msg_type"] == "UAV_FAULT") == 1, "失能注入必须幂等"
    _terminate(client, task_id)


def test_wind_shift_drill_triggers_replan_new_version():
    """FE-35：剧本风变（第 2 轮观测风速 7.5 m/s 跳档）→ wind_band_changed →
    自动生成新方案版本并回到待确认（重规划仍走审批门）。"""
    client = _client()
    task = _create_task(client, people_status="absent", scenario={
        "fire_origin": {"x": 200, "y": 200}, "fire_area_m2": 900,
        "growth_rate": 0.2, "wind_shift": {"round": 2, "speed": 8.5},
    })
    task_id = task["analysis_id"]
    _approve(client, task_id)
    first = client.post(f"/api/tasks/{task_id}/rounds", json={"round": 1, "elapsed_minutes": 5, "extinguishing_liters": 100})
    assert first.status_code == 200
    assert first.json().get("next_action") != "awaiting_confirmation", "第 1 轮不应触发风变"
    second = client.post(f"/api/tasks/{task_id}/rounds", json={"round": 2, "elapsed_minutes": 5, "extinguishing_liters": 100})
    assert second.status_code == 200, second.text
    assert second.json().get("next_action") == "awaiting_confirmation", second.json().get("replan_triggers")
    assert "wind_band_changed" in (second.json().get("replan_triggers") or [])
    envelope = client.get(f"/api/analyze/{task_id}").json()
    assert len(envelope.get("plan_versions") or []) >= 2, "风变后必须生成新方案版本"
    wind_after = (envelope.get("result") or {}).get("environment", {}).get("wind_speed")
    assert wind_after == 8.5, "观测风速必须持久化"
    messages = client.get(f"/api/tasks/{task_id}/agent-messages").json()["items"]
    assert any("跨档变化" in (m.get("content") or "") for m in messages), "缺少观测风变消息"

    # 状态续接（FE-39）：批准 v2 后第 3 轮必须从当前火势继续——
    # 不得回到初始 1800（旧 bug：replan 用陈旧基线，每轮重复触发风变打到 v13）
    client.post(f"/api/tasks/{task_id}/approval", json={"action": "approve", "plan_id": (envelope.get("plan_versions") or [{}])[-1].get("plan_id")})
    baseline = (client.get(f"/api/tasks/{task_id}/plan").json()["plan"] or {}).get("fire_load_flp")
    third = client.post(f"/api/tasks/{task_id}/rounds", json={"round": 3, "elapsed_minutes": 5, "extinguishing_liters": 100})
    assert third.status_code == 200, third.text
    third_body = third.json()
    before3 = (third_body.get("before") or {}).get("fire_load_flp")
    assert before3 == baseline, f"重规划后基线必须等于当前火势 {baseline}（实际 {before3}）"
    assert "wind_band_changed" not in (third_body.get("replan_triggers") or []), "新方案风档已对齐观测，不得再次触发风变"
    _terminate(client, task_id)


def test_scenario_1_absent_baseline_dispatch_and_round():
    client = _client()
    task = _create_task(client, people_status="absent")
    plan = client.get(f"/api/tasks/{task['analysis_id']}/plan").json()["plan"]
    assert plan["selected_uavs"][0].startswith("R")
    support_tasks = [t["task"] for t in plan["tasks"] if t.get("drone_id", "").startswith("S")]
    assert support_tasks and "物流补给" in support_tasks[0]
    assert "agent_allocation" not in plan and "risk_level" not in plan
    assert plan["estimated_control_time"]["unit"] == "min"

    approved = _approve(client, task["analysis_id"])
    assert approved["status"] == "executing" and approved["resource_locks"]

    round_one = client.post(f"/api/tasks/{task['analysis_id']}/rounds",
                            json={"round": 1, "elapsed_minutes": 5, "extinguishing_liters": 20})
    assert round_one.status_code == 200, round_one.text
    assert round_one.json()["next_action"] in {"continue", "resupply", "reinforce", "return", "finish"}
    _terminate(client, task["analysis_id"])


def test_scenario_2_confirmed_people_branch_keeps_support_guidance():
    client = _client()
    task = _create_task(client, people_status="confirmed")
    plan = client.get(f"/api/tasks/{task['analysis_id']}/plan").json()["plan"]
    assert plan["people_branch"] == "confirmed"
    support_tasks = [t["task"] for t in plan["tasks"] if t.get("drone_id", "").startswith("S")]
    assert support_tasks and "通信广播/疏散引导" in support_tasks[0]
    _terminate(client, task["analysis_id"])


def test_scenario_3_wind_band_change_triggers_replan_new_version():
    client = _client()
    task = _create_task(client)
    task_id = task["analysis_id"]
    _approve(client, task_id)
    first_version = client.get(f"/api/tasks/{task_id}/plan").json()["plan"]["plan_version"]

    # 场景默认风速 6.5 m/s 属 6–8 m/s 档；观测 4 m/s 降档触发重规划。
    round_one = client.post(f"/api/tasks/{task_id}/rounds",
                            json={"round": 1, "wind_speed": 4, "elapsed_minutes": 5})
    assert round_one.status_code == 200, round_one.text
    payload = round_one.json()
    assert "wind_band_changed" in payload["replan_triggers"]
    assert payload["next_action"] == "awaiting_confirmation"

    replacement = client.get(f"/api/tasks/{task_id}/plan").json()
    assert replacement["plan"]["plan_version"] == first_version + 1
    assert replacement["plan"]["replan_trigger"] == ["wind_band_changed"]
    assert client.get(f"/api/analyze/{task_id}").json()["resource_locks"] == []
    _terminate(client, task_id)


def test_scenario_5_electrical_fire_with_limited_co2_reports_gap():
    client = _client()
    task = _create_task(client, fire_type="electrical")
    plan = client.get(f"/api/tasks/{task['analysis_id']}/plan").json()["plan"]
    assert plan["material_module"] == "co2_6kg"
    assert plan["can_control"] is False
    assert plan["resource_gap"]
    assert plan["estimated_control_time"]["window_minutes"] is None
    _terminate(client, task["analysis_id"])


def test_scenario_6_reject_adjust_and_terminate_release_locks():
    client = _client()
    task = _create_task(client)
    task_id = task["analysis_id"]
    plan = client.get(f"/api/tasks/{task_id}/plan").json()["plan"]

    rejected = client.post(f"/api/tasks/{task_id}/approval", json={"action": "reject", "plan_id": plan["plan_id"]})
    assert rejected.status_code == 200
    assert rejected.json()["resource_locks"] == []

    adjusted = client.post(f"/api/tasks/{task_id}/approval",
                           json={"action": "adjust", "constraints": {"max_drones": 2},
                                 "idempotency_key": "adjust-scenario"})
    assert adjusted.status_code == 200
    new_plan = adjusted.json()["plan"]
    assert new_plan["plan_version"] == plan["plan_version"] + 1
    assert new_plan["plan_id"] != plan["plan_id"]
    assert len([u for u in new_plan["selected_uavs"] if u.startswith("E")]) <= 2

    approved = client.post(f"/api/tasks/{task_id}/approval", json={"action": "approve", "plan_id": new_plan["plan_id"]})
    assert approved.status_code == 200 and approved.json()["status"] == "executing"
    assert approved.json()["resource_locks"]

    terminated = client.post(f"/api/tasks/{task_id}/approval", json={"action": "terminate", "reason": "场景 6"})
    assert terminated.status_code == 200
    assert terminated.json()["status"] == "terminated"
    assert terminated.json()["resource_locks"] == []
