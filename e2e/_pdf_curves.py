"""PDF 第五部分图 5-2 曲线取证：按 data/frozen_scenarios 三组核心故事真实重跑。

产物：e2e/artifacts/pdf-materials/curves.json（含每轮 before/after FLP、净变化、机群相位、裁决）。
从项目根运行：python e2e/_pdf_curves.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "e2e" / "artifacts" / "pdf-materials"
OUT.mkdir(parents=True, exist_ok=True)
BASE = "http://127.0.0.1:8000"


def api(method: str, path: str, payload: dict | None = None) -> dict:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def phases_of(env: dict) -> dict:
    fleet = (env.get("fleet") or {}).get("uavs") or (env.get("result", {}) or {}).get("fleet", {}).get("uavs") or []
    return {u.get("uav_id") or u.get("id"): u.get("status") for u in fleet}


def run_case(name: str, analyze_body: dict, max_rounds: int, stop_on_completed: bool) -> dict:
    env = api("POST", "/api/analyze", analyze_body)
    task_id = env.get("analysis_id") or env.get("task_id")
    result = env.get("result") or {}
    verdict = {
        "can_control": result.get("can_control"),
        "control_verdict": result.get("control_verdict"),
        "control_reason_code": result.get("control_reason_code"),
        "flp_initial": (result.get("fire_assessment") or {}).get("fire_load_flp"),
        "plan_uavs": len(((result.get("dispatch_plan") or {}).get("selected_uavs")) or []),
    }
    print(f"[{name}] task={task_id} verdict={verdict['control_verdict']} flp0={verdict['flp_initial']} 出动={verdict['plan_uavs']}")

    rounds_series = []
    if name != "C":
        api("POST", f"/api/tasks/{task_id}/approval", {"action": "approve", "reason": "PDF 取证重跑"})
        for n in range(1, max_rounds + 1):
            try:
                env = api("POST", f"/api/tasks/{task_id}/rounds", {"round": n})
            except Exception as e:
                print(f"[{name}] round {n} 异常：{e}")
                break
            status = env.get("status")
            rd = (env.get("rounds") or [{}])[-1]
            before = (rd.get("flp_before") or rd.get("before", {}) or {}).get("fire_load_flp") if isinstance(rd.get("before"), dict) else rd.get("flp_before")
            after = (rd.get("flp_after") or rd.get("after", {}) or {}).get("fire_load_flp") if isinstance(rd.get("after"), dict) else rd.get("flp_after")
            if before is None and isinstance(rd.get("before"), dict):
                before = (rd["before"] or {}).get("flp_ledger", {}).get("total")
            if after is None and isinstance(rd.get("after"), dict):
                after = (rd["after"] or {}).get("flp_ledger", {}).get("total")
            rounds_series.append({
                "round": n,
                "before": before,
                "after": after,
                "net": (after - before) if (before is not None and after is not None) else None,
                "action": rd.get("action") or rd.get("next_action"),
                "triggers": rd.get("triggers"),
                "phases": phases_of(env),
            })
            print(f"[{name}] r{n}: {before} -> {after} (net {rounds_series[-1]['net']}) status={status}")
            if stop_on_completed and status in ("completed", "terminated", "failed"):
                break
            if status == "awaiting_confirmation":
                print(f"[{name}] round {n} 触发重规划回审批门，重新批准")
                api("POST", f"/api/tasks/{task_id}/approval", {"action": "approve", "reason": "重规划后批准"})
    else:
        gaps = (result.get("resource_gaps") or result.get("dispatch_plan", {}).get("resource_gaps") or [])
        verdict["gaps"] = [g if isinstance(g, str) else g.get("reason_code") or g.get("type") for g in gaps][:6]

    return {"name": name, "task_id": task_id, "verdict": verdict, "rounds": rounds_series}


def main() -> int:
    # 前置清场：历史里的非终态任务会占资源锁
    store = api("GET", "/api/analyzes?limit=50&slim=true")
    for it in store.get("items", []):
        if it.get("status") in ("executing", "awaiting_confirmation", "approved", "running", "queued"):
            try:
                api("POST", f"/api/tasks/{it['analysis_id']}/approval", {"action": "terminate", "reason": "取证前清场"})
            except Exception:
                pass

    out = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "cases": []}

    a = run_case("A", {"scene_id": "forest-demo-01", "use_vlm": False, "environment_mode": "offline",
                       "image_name": "small", "people_status": "confirmed"}, max_rounds=30, stop_on_completed=True)
    a["title"] = "核心故事一：成功控制并归档"
    out["cases"].append(a)

    b = run_case("B", {"scene_id": "forest-demo-01", "use_vlm": False, "environment_mode": "offline",
                       "people_status": "absent",
                       "scenario": {"fire_origin": {"x": 150, "y": 150}, "fire_area_m2": 600, "growth_rate": 0.42},
                       "constraints": {"max_drones": 2}}, max_rounds=12, stop_on_completed=True)
    b["title"] = "核心故事二：补给间歇回升"
    out["cases"].append(b)

    c = run_case("C", {"scene_id": "forest-demo-01", "use_vlm": False, "environment_mode": "offline",
                       "image_name": "large-fire", "people_status": "unknown"}, max_rounds=0, stop_on_completed=False)
    c["title"] = "核心故事三：资源不足诚实增援"
    out["cases"].append(c)

    (OUT / "curves.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("saved =>", OUT / "curves.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
