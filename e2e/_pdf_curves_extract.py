"""从已重跑的 A/B/C 任务信封提取图 5-2 曲线数据（修正信封导航版）。

产物：e2e/artifacts/pdf-materials/curves.json
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

TASKS = {
    "A": ("analysis-f59c7dc7ab53", "核心故事一：成功控制并归档"),
    "B": ("analysis-03c693be4d22", "核心故事二：补给间歇回升"),
    "C": ("analysis-2440a2d66b32", "核心故事三：资源不足诚实增援"),
}


def get(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=60) as r:
        return json.loads(r.read().decode())


def main() -> int:
    out = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "cases": []}
    for key, (task_id, title) in TASKS.items():
        env = get(f"/api/analyze/{task_id}")
        res = env.get("result") or {}
        plan = res.get("dispatch_plan") or {}
        fa = res.get("fire_assessment") or {}
        rounds = []
        for rd in env.get("rounds") or []:
            before = (rd.get("before") or {}).get("fire_load_flp")
            after = (rd.get("after") or {}).get("fire_load_flp")
            fleet = (rd.get("after") or {}).get("fleet") or {}
            uavs = fleet.get("uavs") if isinstance(fleet, dict) else fleet
            uavs = uavs or []
            phase_count = {}
            for u in uavs:
                phase_count[u.get("status")] = phase_count.get(u.get("status"), 0) + 1
            rounds.append({
                "round": rd.get("round"),
                "before": before,
                "after": after,
                "net": (after - before) if before is not None and after is not None else None,
                "growth_rate": (rd.get("before") or {}).get("growth_rate"),
                "action": rd.get("next_action"),
                "triggers": rd.get("replan_triggers"),
                "phases": phase_count,
            })
        gaps = plan.get("resource_gaps") or (res.get("monitor") or {}).get("resource_gap") or []
        out["cases"].append({
            "key": key,
            "title": title,
            "task_id": task_id,
            "status": env.get("status"),
            "flp_initial": (rounds[0]["before"] if rounds else None) or fa.get("fire_load_flp"),
            "fire_level": fa.get("label"),
            "plan_uavs": len(plan.get("selected_uavs") or []),
            "can_control": plan.get("can_control"),
            "control_verdict": plan.get("control_verdict"),
            "control_reason_code": plan.get("control_reason_code"),
            "time_window": [plan.get("earliest_minutes"), plan.get("latest_minutes")],
            "gaps": gaps if isinstance(gaps, list) else [gaps],
            "rounds": rounds,
        })
        print(f"[{key}] status={env.get('status')} flp0={fa.get('fire_load_flp')} verdict={plan.get('control_verdict')} "
              f"rounds={len(rounds)} net_series={[r['net'] for r in rounds]}")

    (OUT / "curves.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("saved =>", OUT / "curves.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
