"""第 14 轮：分层架构冒烟——rules/domain/agents 分层后端到端（随机场景 → 分析 → 消息）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import Session, report  # noqa: E402


def main() -> int:
    session = Session()
    ok = True
    detail = ""
    page = session.page
    try:
        session.goto_app()

        # rules/domain 分层：随机场景由后端生成
        scenario = session.api("GET", "/api/scenarios/random")
        scenario_body = scenario["scenario"]
        ok &= report(14, "后端随机场景生成", 300 <= scenario_body["fire_area_m2"] <= 6000
                     and -1000 <= scenario_body["fire_origin"]["y"] <= 800, str(scenario_body)[:100])

        # scenario 驱动研判（agents/graph 编排）
        payload = {
            "scene_id": "forest-demo-01",
            "latitude": scenario_body["fire_origin_gps"]["latitude"],
            "longitude": scenario_body["fire_origin_gps"]["longitude"],
            "environment_mode": "offline",
            "people_status": scenario_body["people_status"],
            "scenario": {"fire_origin": scenario_body["fire_origin"],
                         "fire_area_m2": scenario_body["fire_area_m2"],
                         "growth_rate": scenario_body["growth_rate"]},
        }
        result = session.api("POST", "/api/analyze", payload)
        aid = result["analysis_id"]
        fire = result["result"]["fire_assessment"]
        ok &= report(14, "场景驱动研判", fire["fire_area_m2"] == scenario_body["fire_area_m2"],
                     f"area={fire['fire_area_m2']} flp={fire['fire_load_flp']}")
        ok &= report(14, "火点 GPS 锚点反演", result["result"]["scene"]["fire_origin_gps"]["latitude"] == scenario_body["fire_origin_gps"]["latitude"])

        # Agent 协作消息（黑板层）
        messages = session.api("GET", f"/api/tasks/{aid}/agent-messages")["items"]
        types = [m["msg_type"] for m in messages]
        ok &= report(14, "六角色协作消息", "TASK_ASSIGN" in types and "FINDING" in types and "PLAN_PROPOSAL" in types and "APPROVAL_REQ" in types, str(types))

        # UI：消息经 REST 可回放（R13 已覆盖页面渲染）
        rendered = session.api("GET", f"/api/tasks/{aid}/agent-messages")
        ok &= report(14, "协作消息可回放", len(rendered["items"]) == len(messages))

        session.api("POST", f"/api/tasks/{aid}/approval", {"action": "terminate", "reason": "round14 cleanup"})
    except Exception as error:
        ok = False
        detail = f"{type(error).__name__}: {str(error)[:260]}"
        session.screenshot("round14_failure")
    finally:
        session.cleanup_task()
        session.close(ok)
    if not ok:
        print("detail:", detail)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
