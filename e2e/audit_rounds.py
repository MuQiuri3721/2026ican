"""逐轮实际驱动模拟火情任务，审计灭火/研判/资源全链路（对齐前端真实调用形态，BE-12/FE-41 验证工具）。

场景：
  A 小火全生命周期（应扑灭归档：finish/锁释放/报告/终态 409）
  B 失能+风变演练（补位/重规划续接/方案版本严格递增）
  C 大火失控（方案基线累计涨幅触发器必须兜底 → 重规划可见）
用法：python -u e2e/audit_rounds.py
  默认打 127.0.0.1:8000；设 FIREOPS_AUDIT_BASE（如 http://127.0.0.1:8001）
  配合 FIREOPS_DB_PATH 隔离库实例，避免与用户/并行会话互踩任务与锁。
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.environ.get("FIREOPS_AUDIT_BASE", "http://127.0.0.1:8000")
ART = Path(__file__).parent / "artifacts"
ART.mkdir(exist_ok=True)
PHASES = {"available", "assigned", "flying", "working", "returning", "servicing", "charging", "fault"}


def req(method, path, payload=None, timeout=180):
    data = json.dumps(payload).encode() if payload is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            raw = json.loads(raw)
        except Exception:
            pass
        return exc.code, raw


ISSUES = []
OKS = [0]


def check(cond, msg):
    if cond:
        OKS[0] += 1
        print(f"  [OK ] {msg}")
    else:
        print(f"  [!!] {msg}")
        ISSUES.append(msg)


def terminate(tid):
    req("POST", f"/api/tasks/{tid}/approval", {"action": "terminate", "reason": "audit cleanup"})


def judge_messages(tid):
    st, msgs = req("GET", f"/api/tasks/{tid}/agent-messages?after_seq=0")
    if st != 200:
        return []
    items = msgs if isinstance(msgs, list) else msgs.get("messages", msgs.get("items", []))
    return [m for m in items if m.get("msg_type") == "JUDGMENT"]


def audit_round(rnd, round_data, prev_after_flp, prev_water):
    before = round_data.get("before") or {}
    after = round_data.get("after") or {}
    flp_b, flp_a = before.get("fire_load_flp"), after.get("fire_load_flp")
    action = after.get("action")
    triggers = round_data.get("replan_triggers") or []
    fleet = after.get("fleet") or []
    inv = after.get("inventory") or {}
    area = after.get("next_fire_area_m2")
    print(f"  R{rnd}: FLP {flp_b} -> {flp_a}  面积≈{area}  action={action}  next={round_data.get('next_action')}  触发器={triggers}")
    e_units = [u for u in fleet if str(u.get("uav_id", "")).startswith("E")]
    print("       E机: " + " | ".join(
        f"{u['uav_id']} {u.get('status')}/SOC{u.get('soc')}/药{u.get('agent_remaining')}" for u in e_units))
    print(f"       水={inv.get('water_liters')}L W20={inv.get('water_modules_w20')} 电池={inv.get('battery_packs')}  本轮喷洒={after.get('resource_consumed', {}).get('water_liters')}L")
    if flp_a is None or flp_a < 0:
        check(False, f"R{rnd} FLP 非负")
    if prev_after_flp is not None:
        check(abs(flp_b - prev_after_flp) < 0.51, f"R{rnd} 轮首 FLP 续接上轮末（{flp_b} vs {prev_after_flp}）")
    for u in fleet:
        if u.get("status") not in PHASES:
            check(False, f"R{rnd} {u.get('uav_id')} 相位非法({u.get('status')})")
        if not (0 <= (u.get("soc") or 0) <= 100):
            check(False, f"R{rnd} {u.get('uav_id')} SOC 越界({u.get('soc')})")
    if prev_water is not None and inv.get("water_liters") is not None:
        if inv["water_liters"] < -1e-6:
            check(False, f"R{rnd} 库存水为负（{inv['water_liters']}）")
        # BE-14 余水退库（规则1 §5.2 Returned_unused）：落场机的机上余水会回注库存，
        # 单轮回升合法但上限 = 灭火机数 × 单模块 20L（全部落场且满退的物理上限）。
        if inv["water_liters"] > prev_water + 20 * max(len(fleet), 1) + 1e-6:
            check(False, f"R{rnd} 库存水异常回升（{prev_water}->{inv['water_liters']}，超过全队退库物理上限）")
    return {"round": rnd, "flp_before": flp_b, "flp_after": flp_a, "action": action,
            "triggers": triggers, "next_action": round_data.get("next_action"),
            "area": area, "water": inv.get("water_liters")}


def run_mission(name, scenario, max_rounds=40, expect="extinguish", people_status="confirmed"):
    print(f"\n===== {name} =====")
    st, created = req("POST", "/api/analyze", {
        "scene_id": "forest-demo-01", "people_status": people_status,
        "fire_type": "vegetation", "scenario": scenario})
    if st != 200:
        check(False, f"{name}: 创建失败 {st} {created}")
        return None
    tid = created["analysis_id"]
    dp = created["result"]["dispatch_plan"]
    fa = created["result"]["fire_assessment"]
    trace = {"task_id": tid, "name": name, "rounds": [], "replans": [], "judgments": 0}
    print(f"task={tid}  FLP={dp['fire_load_flp']} growth={dp.get('growth_flp_per_hour')}/h  出动={dp['selected_uavs']}")
    print(f"       研判: 面积={fa['fire_area_m2']}m² FLP={fa['fire_load_flp']} 比率={fa.get('area_per_flp')}m²/FLP  {fa['label']}  可控={dp.get('can_control')}")
    check(fa.get("area_per_flp") is not None, "研判携带 area_per_flp（BE-12 口径锚点）")
    try:
        st, ap = req("POST", f"/api/tasks/{tid}/approval",
                     {"action": "approve", "plan_id": dp.get("plan_id"), "reason": "audit"})
        check(st == 200 and ap.get("status") == "executing", f"批准 → executing（got {st} {ap.get('detail') or ap.get('status')}）")
        if st != 200:
            return trace

        prev_after_flp = prev_water = None
        rnd = 0
        while rnd < max_rounds:
            st, env = req("GET", f"/api/analyze/{tid}")
            status = env.get("status")
            if status == "completed":
                print("  -- 任务已完成（扑灭归档）--")
                break
            if status == "awaiting_confirmation":
                st2, plan = req("GET", f"/api/tasks/{tid}/plan")
                new_dp = plan.get("plan") or {}
                new_v = new_dp.get("plan_version")
                last = trace["rounds"][-1] if trace["rounds"] else {}
                print(f"  -- 重规划待审批: v{new_v} trigger={new_dp.get('replan_trigger')} 新基线FLP={new_dp.get('fire_load_flp')}")
                check(new_v == len(plan.get("versions", [])), f"方案版本=最新（v{new_v}）")
                if last.get("flp_after") is not None:
                    check(abs((new_dp.get("fire_load_flp") or 0) - last["flp_after"]) < 0.51,
                          f"重规划 v{new_v} 续接当前 FLP（{new_dp.get('fire_load_flp')} vs {last['flp_after']}）——FE-39")
                trace["replans"].append({"version": new_v, "trigger": new_dp.get("replan_trigger"),
                                         "flp": new_dp.get("fire_load_flp"), "selected": new_dp.get("selected_uavs")})
                st3, ap2 = req("POST", f"/api/tasks/{tid}/approval",
                               {"action": "approve", "plan_id": new_dp.get("plan_id"), "reason": "audit-replan"})
                check(st3 == 200 and ap2.get("status") == "executing",
                      f"重规划 v{new_v} 批准（got {st3} {ap2.get('detail') or ap2.get('status')}）")
                if st3 != 200:
                    return trace
                continue
            if status != "executing":
                print(f"  -- 状态 {status}，停止轮次 --")
                break
            rnd += 1
            st4, resp = req("POST", f"/api/tasks/{tid}/rounds",
                            {"round": rnd, "elapsed_minutes": 5, "extinguishing_liters": 0})
            if st4 != 200:
                check(False, f"{name} R{rnd} 轮次失败 {st4}: {resp}")
                break
            obs = audit_round(rnd, resp, prev_after_flp, prev_water)
            trace["rounds"].append(obs)
            prev_after_flp, prev_water = obs["flp_after"], obs["water"]

        # 终态/收尾断言
        st5, env = req("GET", f"/api/analyze/{tid}")
        trace["final_status"] = env.get("status")
        trace["judgments"] = len(judge_messages(tid))
        print(f"  研判消息总数={trace['judgments']}（>1 即 judge 不再 R2 消失——BE-12 ①）")
        if expect == "extinguish":
            check(env.get("status") == "completed", f"小火应扑灭归档（实际 {env.get('status')}，{len(trace['rounds'])} 轮）")
            check(trace["judgments"] >= 2, f"研判消息 ≥2（实际 {trace['judgments']}）")
            check(not env.get("resource_locks"), f"completed 后锁已释放（{env.get('resource_locks')}）")
            st6, _ = req("POST", f"/api/tasks/{tid}/rounds", {"round": 99, "elapsed_minutes": 5})
            check(st6 == 409, f"终态后再报轮次被拒（{st6}）")
            st7, _ = req("POST", f"/api/tasks/{tid}/approval", {"action": "approve"})
            check(st7 == 409, f"终态后再审批被拒（{st7}）")
            st8, _ = req("GET", f"/api/tasks/{tid}/report")
            check(st8 == 200, f"结案报告可下载（{st8}）")
        elif expect == "runaway":
            hits = [t for r in trace["rounds"] for t in (r["triggers"] or []) if t == "fire_load_increase_over_20_percent"]
            check(len(trace["replans"]) >= 1 or hits or env.get("status") == "awaiting_confirmation",
                  f"大火失控必须触发累计涨幅重规划（重规划 {len(trace['replans'])} 次，触发器 {hits}）")
            print(f"  失控场景终态={env.get('status')} 重规划={len(trace['replans'])}（安全网兜底即合格）")
        else:
            check(trace["judgments"] >= 2, f"演练场景研判消息 ≥2（实际 {trace['judgments']}）")
    finally:
        terminate(tid)
    print(f"  小结：轮数={len(trace['rounds'])} 重规划={len(trace['replans'])}")
    return trace


def main():
    started = time.time()
    traces = {}
    # A 小火：~500m²（编队容量内），应扑灭——验证全生命周期
    traces["small"] = run_mission(
        "A 小火全生命周期", {"fire_origin": {"x": 900, "y": 600}, "fire_area_m2": 500, "growth_rate": 0.4},
        max_rounds=60, expect="extinguish")
    # B 演练：失能 R2 + 风变 R3（6.5 基线在 2 档，8.6 跨 3 档）
    traces["drill"] = run_mission(
        "B 失能+风变演练", {"fire_origin": {"x": -600, "y": 300}, "fire_area_m2": 1600, "growth_rate": 0.5,
                            "uav_failure_round": 2, "wind_shift": {"round": 3, "speed": 8.6}},
        max_rounds=30, expect="drill")
    # C 大火：增长远超压制，安全网必须兜底
    traces["runaway"] = run_mission(
        "C 大火失控安全网", {"fire_origin": {"x": 1100, "y": 850}, "fire_area_m2": 4000, "growth_rate": 0.9},
        max_rounds=12, expect="runaway")
    (ART / "audit_rounds.json").write_text(json.dumps(
        {"traces": traces, "issues": ISSUES, "oks": OKS[0], "elapsed_s": round(time.time() - started, 1)},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n===== 审计结论：{OKS[0]} 项通过，{'无问题' if not ISSUES else f'{len(ISSUES)} 个问题'}（耗时 {time.time()-started:.0f}s）=====")
    for i, issue in enumerate(ISSUES, 1):
        print(f"  {i}. {issue}")
    return 1 if ISSUES else 0


if __name__ == "__main__":
    sys.exit(main())
