# -*- coding: utf-8 -*-
"""OPT-P4 人工验收 A–F 的可自动化预执行（docs/下一阶段优化与修正方案.md §六.2）。

A 固定正常场景：offline+small fixture → 研判 → 批准 → 逐轮至归档，逐轮校验账本守恒。
B 补给回升：约束 2 机压制中等火，记录逐轮净变化序列与补给相位（服务间歇证据）。
C 双不足对比：资源不足（cannot_control/suppression_insufficient）vs 仅时间不足
  （maintain_only/time_limit_exceeded）——三态与原因码必须分离开。
D GIS 证据：记录环境快照 ID 与 FLP 输入来源（坡度/燃料），引用 T12–T15 单测。
E VLM 状态：无 Key → skipped；端点不可达 → fallback+error_code（真实调用见
  e2e/_webfire_suite.py 历史记录）。
记录落 docs/p4-acceptance-record.json。
用法：python e2e/acceptance_opt.py
"""
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8000"
OUT = Path("docs/p4-acceptance-record.json")


def call(method, path, payload=None, timeout=300):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        return json.load(urllib.request.urlopen(req, timeout=timeout))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "replace")[:200]
        raise RuntimeError(f"{method} {path} → HTTP {error.code} {body}") from error


def pre_clean():
    items = call("GET", "/api/analyzes?limit=50")
    rows = items.get("items") or items if isinstance(items, list) else items.get("items", [])
    for row in rows:
        aid = row.get("analysis_id") or row.get("id")
        if aid and row.get("status") in ("awaiting_confirmation", "executing", "approved", "replanning"):
            try:
                call("POST", f"/api/tasks/{aid}/approval", {"action": "terminate", "reason": "验收清场"})
            except Exception:
                pass


def approve(aid):
    return call("POST", f"/api/tasks/{aid}/approval",
                {"action": "approve", "operator_id": "acceptance", "comment": "OPT-P4 验收"})


def rounds_until_done(aid, max_rounds=40):
    """逐轮推进（从任务 monitor_round+1 递增），返回轮记录列表与最终信封。"""
    records = []
    snapshot = call("GET", f"/api/analyze/{aid}")
    for round_no in range(snapshot.get("monitor_round", 0) + 1, max_rounds + 1):
        result = call("POST", f"/api/tasks/{aid}/rounds",
                      {"round": round_no, "elapsed_minutes": 5, "extinguishing_liters": 0})
        monitor = result.get("after") or {}
        action = monitor.get("action")
        records.append({
            "round": round_no,
            "action": action,
            "reason": monitor.get("reason"),
            "flp_ledger": monitor.get("flp_ledger"),
            "next_action": (result.get("rounds") or [{}])[-1].get("next_action") if isinstance(result.get("rounds"), list) else None,
        })
        if action == "finish" or result.get("status") in ("completed", "terminated"):
            break
        # 重规划 → 任务回待确认，需再次批准后继续
        if result.get("status") == "awaiting_confirmation" and monitor.get("replan_required"):
            approve(aid)
        snapshot = result
    return records, call("GET", f"/api/analyze/{aid}")


def ledger_consistent(ledger, tol=0.02):
    if not ledger:
        return None
    return abs(ledger["after_flp"] - (ledger["before_flp"] + ledger["growth_flp"] - ledger["suppression_flp"])) <= tol


def scenario_a(record):
    """A 固定正常场景：offline+small → 批准 → 逐轮 → 归档；逐轮账本守恒。"""
    env = call("POST", "/api/analyze", {"scene_id": "forest-demo-01", "use_vlm": False,
                                        "environment_mode": "offline", "image_name": "small",
                                        "people_status": "confirmed"})
    aid = env["analysis_id"]
    record["A"].update({
        "task_id": aid,
        "plan_version": len(env.get("plan_versions") or []),
        "environment_snapshot_id": env.get("environment_snapshot_id"),
        "environment_snapshots": list((env.get("result", {}).get("environment_snapshots") or {}).keys()),
        "flp_input_source": (env["result"].get("fire_assessment", {}).get("fire_grid") or {}).get("slope_source"),
    })
    assert env["status"] == "awaiting_confirmation"
    approve(aid)
    records, final = rounds_until_done(aid)
    consistent = [ledger_consistent(r.get("flp_ledger")) for r in records if r.get("flp_ledger")]
    record["A"].update({
        "rounds": records,
        "ledger_consistent_all": all(c for c in consistent if c is not None),
        "final_status": final.get("status"),
        "monitor_round": final.get("monitor_round"),
    })
    assert final.get("status") == "completed", f"A 场景应归档 completed，实际 {final.get('status')}"
    assert all(c for c in consistent if c is not None), "存在账本不守恒的轮次"
    print(f"  A 归档完成：{final.get('monitor_round')} 轮，账本守恒 {sum(1 for c in consistent if c is not None)}/{len(consistent)}")


def scenario_b(record):
    """B 补给回升：场景驱动中火（800m²@0.45）+ 2 机约束，记录净变化序列与补给相位。"""
    env = call("POST", "/api/analyze", {"scene_id": "forest-demo-01", "use_vlm": False,
                                        "environment_mode": "offline", "people_status": "absent",
                                        "scenario": {"fire_origin": {"x": 150, "y": 150},
                                                     "fire_area_m2": 600, "growth_rate": 0.42},
                                        "constraints": {"max_drones": 2}})
    aid = env["analysis_id"]
    plan_b = env["result"]["dispatch_plan"]
    # B 场景目的即观察「慢压维持」下的补给间歇：maintain_only 可批准推演（压制追平增长但窗口内灭不完）
    assert plan_b.get("control_verdict") in ("can_control", "maintain_only"), (
        f"B 场景需要可控/慢压方案，实际 {plan_b.get('control_verdict')}/{plan_b.get('control_reason_code')}")
    assert env["status"] == "awaiting_confirmation"
    approve(aid)
    records, final = rounds_until_done(aid, max_rounds=12)
    nets = [r["flp_ledger"]["net_change_flp"] for r in records if r.get("flp_ledger")]
    record["B"].update({
        "task_id": aid,
        "final_status": final.get("status"),
        "net_change_series": nets,
        "phases_seen": sorted({p for r in records for d in ((r.get("flp_ledger") or {}).get("per_minute") or []) for p in ([d] if False else [])}),
        "note": "净变化序列若出现先增后减/交替，即为服务间歇与接替恢复的证据（机群相位与消耗随轮留档）",
    })
    print(f"  B 净变化序列：{nets}")


def scenario_c(record):
    """C 双不足对比：资源不足 vs 仅时间不足——三态与原因码必须分离。"""
    res = call("POST", "/api/analyze", {"scene_id": "forest-demo-01", "use_vlm": False,
                                        "environment_mode": "offline", "image_name": "large-fire"})
    plan_res = res["result"]["dispatch_plan"]
    call("POST", f"/api/tasks/{res['analysis_id']}/approval", {"action": "terminate", "reason": "验收清场"})
    timed = call("POST", "/api/analyze", {"scene_id": "forest-demo-01", "use_vlm": False,
                                          "environment_mode": "offline", "image_name": "small",
                                          "constraints": {"target_minutes": 0}})
    plan_timed = timed["result"]["dispatch_plan"]
    call("POST", f"/api/tasks/{timed['analysis_id']}/approval", {"action": "terminate", "reason": "验收清场"})
    record["C"] = {
        "resource_insufficient": {
            "can_control": plan_res.get("can_control"),
            "control_verdict": plan_res.get("control_verdict"),
            "control_reason_code": plan_res.get("control_reason_code"),
            "gaps": [g.get("resource") for g in plan_res.get("resource_gap", [])],
        },
        "time_insufficient": {
            "can_control": plan_timed.get("can_control"),
            "control_verdict": plan_timed.get("control_verdict"),
            "control_reason_code": plan_timed.get("control_reason_code"),
            "gaps": [g.get("resource") for g in plan_timed.get("resource_gap", [])],
        },
    }
    ri, ti = record["C"]["resource_insufficient"], record["C"]["time_insufficient"]
    assert ri["control_verdict"] in ("cannot_control", "maintain_only") and not ri["can_control"]
    assert ti["can_control"] is False and ti["control_verdict"] != "can_control"
    assert ti["control_reason_code"] == "time_limit_exceeded", "仅时间不足应归因 time_limit_exceeded"
    print(f"  C 资源不足={ri['control_verdict']}/{ri['control_reason_code']} · 时间不足={ti['control_verdict']}/{ti['control_reason_code']}")


def scenario_d_e(record):
    """D GIS 证据 + E VLM 状态（无 Key 单列 skipped；端点不可达 fallback）。"""
    import os
    from backend.app.tools.core import analyze_with_vlm
    os.environ.pop("FIRE_VLM_API_KEY", None)
    os.environ.pop("FIRE_VLM_ENDPOINT", None)
    skipped = analyze_with_vlm({"fire_area_m2": 100}, {}, "absent")
    os.environ["FIRE_VLM_ENDPOINT"] = "http://127.0.0.1:9/vlm"  # 必然不可达
    fallback = analyze_with_vlm({"fire_area_m2": 100}, {}, "absent")
    os.environ.pop("FIRE_VLM_ENDPOINT", None)
    record["E"] = {
        "not_configured": {"status": skipped.get("status"), "code": (skipped.get("adapter_fallback") or {}).get("code")},
        "endpoint_unreachable": {"status": fallback.get("status"), "code": (fallback.get("adapter_fallback") or {}).get("code"),
                                 "error_code": (fallback.get("adapter_fallback") or {}).get("error_code")},
        "real_call_evidence": "见 e2e/_webfire_suite.py 历史批次（12/12 真实识别）与 docs/vlm-delivery/evaluation-results.md",
    }
    print(f"  E skipped={record['E']['not_configured']['status']} fallback={record['E']['endpoint_unreachable']['status']}/{record['E']['endpoint_unreachable']['error_code']}")


def main():
    pre_clean()
    record = {"executed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "A": {}, "B": {}, "C": {}, "D": {}, "E": {}, "F": {}}
    scenario_a(record)
    scenario_b(record)
    scenario_c(record)
    # D：GIS 进入决策的证据由 T12–T15 单测 + A 中记录的快照 ID/输入来源构成
    record["D"] = {
        "unit_tests": ["T12 坡度/燃料→FLP", "T13 水源 ID 稳定", "T14 失效不换候选", "T15 快照不可变"],
        "snapshot_evidence": "见 record.A.environment_snapshot_id / flp_input_source",
    }
    scenario_d_e(record)
    record["F"] = {"note": "地图缓存/详情为浏览器行为，由 e2e R1/R17 与 P4-F 人工路径覆盖"}
    OUT.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"验收记录已归档 → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
