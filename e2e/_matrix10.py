# 10 轮不同火情算法压测：覆盖面积/增长率/人员状态/风变/失能/零增长/编成极限。
# 每轮：API 造任务 → 批准 → 循环推演至扑灭或 20 轮 → 采集裁决一致性/SOC 硬线/扩编/重规划风暴。
import json
import time
import urllib.request

BASE = "http://127.0.0.1:8000"


def api(method, path, payload=None, timeout=120):
    req = urllib.request.Request(BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


MATRIX = [
    ("1 微火速胜",   250,  0.10, "absent",   {}),
    ("2 小火标准",   450,  0.18, "absent",   {}),
    ("3 余烬零增长", 800,  0.00, "unknown",  {}),
    ("4 小火慢压",   900,  0.30, "unknown",  {}),
    ("5 中火有人",   1500, 0.35, "confirmed", {}),
    ("6 中火扰动",   1800, 0.45, "unknown",  {"uav_failure_round": 4}),
    ("7 大火无人",   3000, 0.40, "absent",   {}),
    ("8 大火快涨",   4500, 0.60, "unknown",  {}),
    ("9 超大火极限", 8000, 0.50, "unknown",  {}),
    ("10 强风快涨",  2500, 0.80, "confirmed", {"wind_shift": {"round": 3, "speed": 8.6}}),
]

results = []
for name, area, rate, people, extra in MATRIX:
    t0 = time.time()
    scenario = {"fire_origin": {"x": 60, "y": -120}, "fire_area_m2": area, "growth_rate": rate, **extra}
    env = api("POST", "/api/analyze", {
        "scene_id": "forest-demo-01", "use_vlm": False,
        "people_status": people, "scenario": scenario,
    })
    tid = env.get("analysis_id")
    v1 = env.get("result", {}).get("dispatch_plan") or {}
    ff1 = v1.get("firefighting_uavs") or []
    v1_verdict = v1.get("control_verdict")
    api("POST", f"/api/tasks/{tid}/approval", {"action": "approve"})

    finished_round, versions_max, expand_ev, soc_min, nets = None, 1, "", 100.0, []
    for rd in range(1, 21):
        try:
            api("POST", f"/api/tasks/{tid}/rounds", {"round": rd, "elapsed_minutes": 5})
        except Exception as e:
            finished_round = f"round{rd}异常:{str(e)[:40]}"
            break
        d = api("GET", f"/api/analyze/{tid}")
        st = d.get("status")
        versions_max = max(versions_max, len(d.get("plan_versions") or []))
        rounds = d.get("rounds") or []
        last = rounds[-1] if rounds else {}
        led = (last.get("after") or {}).get("flp_ledger") or {}
        if led:
            g, s = float(led.get("growth_flp") or 0), float(led.get("suppression_flp") or 0)
            nets.append(round(g - s, 1))
        for u in (d.get("result") or {}).get("fleet") or []:
            if u.get("status") == "flying":
                soc_min = min(soc_min, float(u.get("soc") or 0))
        if not expand_ev and any("扩编" in (e.get("message") or "") for e in (d.get("events") or [])):
            expand_ev = f"R{rd}扩编"
        if st == "completed":
            finished_round = rd
            break
        if st in {"awaiting_confirmation", "replanning"}:
            # 二次审批：扩编方案自动批准继续（测闭环本身）
            api("POST", f"/api/tasks/{tid}/approval", {"action": "approve"})
    d = api("GET", f"/api/analyze/{tid}")
    dp = (d.get("result") or {}).get("dispatch_plan") or {}
    final = {
        "name": name, "area": area, "rate": rate, "people": people,
        "v1_ff": len(ff1), "v1_verdict": v1_verdict,
        "final_status": d.get("status"), "finish_round": finished_round,
        "versions": versions_max, "expand": expand_ev or "无",
        "soc_min_flying": round(soc_min, 1),
        "verdict_final": dp.get("control_verdict"),
        "reason": dp.get("control_reason_code"),
        "water": dp.get("resource_consumed", {}).get("water_liters") if isinstance(dp.get("resource_consumed"), dict) else None,
        "secs": round(time.time() - t0, 1),
    }
    results.append(final)
    print(json.dumps(final, ensure_ascii=False), flush=True)
    try:
        api("POST", f"/api/tasks/{tid}/approval", {"action": "terminate", "reason": "矩阵测试清理"})
    except Exception:
        pass

print("\n===== 分析 =====")
for f in results:
    flags = []
    if f["v1_verdict"] == "can_control" and f["final_status"] != "completed":
        flags.append("裁决虚高?can_control未灭")
    if f["soc_min_flying"] < 25:
        flags.append(f"SOC破硬线{f['soc_min_flying']}")
    if f["versions"] >= 4:
        flags.append(f"重规划风暴v{f['versions']}")
    print(f"{f['name']}: {f['v1_verdict']}(v1:{f['v1_ff']}架) → {f['final_status']} 轮={f['finish_round']} v{f['versions']} 扩编={f['expand']} SOC最低={f['soc_min_flying']} {'⚠ ' + ';'.join(flags) if flags else '✓'}")
