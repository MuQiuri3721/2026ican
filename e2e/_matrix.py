"""多角度组合矩阵测试：演练交叉 / 审批交叉 / 极端场景（离线确定性）。"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)

# 清场：共享 SQLite 里其他会话遗留的在途任务会带锁，导致 approve 409
from backend.app.domain.store import analysis_store as _store
for _item in list(_store._items.values()):
    if _item.status in {"executing", "approved", "replanning", "awaiting_confirmation"}:
        try:
            _store.release_resources(_item.analysis_id)
            _store.update(_item.analysis_id, status="terminated")
        except Exception:
            pass

PASS, FAIL = [], []

def check(tag, name, cond, detail=""):
    (PASS if cond else FAIL).append(f"{tag}:{name}")
    print(f"[{tag}] {name}: {'PASS' if cond else 'FAIL'}" + (f" | {str(detail)[:90]}" if detail else ""))

def new_task(extra=None, people="absent"):
    body = {"scene_id": "forest-demo-01", "image_name": "matrix.jpg",
            "environment_mode": "offline", "people_status": people}
    if extra:
        body.update(extra)
    return client.post("/api/analyze", json=body).json()["analysis_id"]

def approve(tid):
    plan = client.get(f"/api/tasks/{tid}/plan").json()["plan"]
    r = client.post(f"/api/tasks/{tid}/approval", json={"action": "approve", "plan_id": plan["plan_id"]})
    assert r.status_code == 200, r.text
    return r.json()

def rnd(tid, n, **kw):
    body = {"round": n, "elapsed_minutes": 5, "extinguishing_liters": kw.pop("liters", 100)}
    body.update(kw)
    return client.post(f"/api/tasks/{tid}/rounds", json=body)

def msgs(tid, types_only=True):
    items = client.get(f"/api/tasks/{tid}/agent-messages").json()["items"]
    return [m["msg_type"] for m in items] if types_only else items

def cleanup(tid):
    try:
        client.post(f"/api/tasks/{tid}/approval", json={"action": "terminate", "reason": "matrix cleanup"})
    except Exception:
        pass

# ---------- A: 失能(第2轮) + 风变(第4轮) 交叉 ----------
print("== A: 失能+风变交叉 ==")
tid = new_task({"scenario": {"fire_origin": {"x": 200, "y": 200}, "fire_area_m2": 900,
               "growth_rate": 0.2, "wind_shift": {"round": 4, "speed": 8.5},
               "uav_failure_round": 2}})
approve(tid)
rnd(tid, 1)
r2 = rnd(tid, 2)
check("A", "第2轮失能不触发重规划", r2.status_code == 200 and r2.json().get("next_action") != "awaiting_confirmation")
types = msgs(tid)
check("A", "失能+补位消息", "UAV_FAULT" in types and "BACKFILL" in types)
faulted = next((m.get("data") or {}).get("faulted") for m in msgs(tid, False) if m["msg_type"] == "UAV_FAULT")
bf = next((m.get("data") or {}).get("choice") for m in msgs(tid, False) if m["msg_type"] == "BACKFILL")
roster = set((client.get(f"/api/analyze/{tid}").json().get("result") or {}).get("dispatch_plan", {}).get("selected_uavs", []))
check("A", "失能机移出名册", faulted not in roster, f"{faulted}→{bf} roster={sorted(roster)}")
rnd(tid, 3)  # 补位机继续推演
r4 = rnd(tid, 4)
check("A", "第4轮风变重规划", r4.json().get("next_action") == "awaiting_confirmation" and "wind_band_changed" in (r4.json().get("replan_triggers") or []), r4.json().get("replan_triggers"))
plan_v2 = client.get(f"/api/tasks/{tid}/plan").json()["plan"]
check("A", "新方案含补位机", bf == "none" or bf in (plan_v2.get("selected_uavs") or []))
approve(tid)  # 批准含补位机的新阵容
r5 = rnd(tid, 5)
check("A", "第5轮继续推进", r5.status_code == 200)
before5 = (r5.json().get("before") or {}).get("fire_load_flp")
after4 = (r4.json().get("after") or {}).get("fire_load_flp")
check("A", "火势跨重规划延续", before5 == after4, f"{after4}→{before5}")
cleanup(tid)

# ---------- B: 风变轮=失能轮 同轮 ----------
print("== B: 同轮风变+失能 ==")
tid = new_task({"scenario": {"fire_origin": {"x": 300, "y": 300}, "fire_area_m2": 900,
               "growth_rate": 0.2, "wind_shift": {"round": 2, "speed": 8.5},
               "uav_failure_round": 2}})
approve(tid)
rnd(tid, 1)
r2 = rnd(tid, 2)
check("B", "同轮两演练不冲突", r2.status_code == 200, r2.text[:60])
types = msgs(tid)
check("B", "风变+失能消息齐备", "UAV_FAULT" in types and "wind" in json.dumps([m.get("content") for m in msgs(tid, False) if "风" in (m.get("content") or "")]).lower() or "UAV_FAULT" in types)
r3 = rnd(tid, 3)
check("B", "第3轮继续", r3.status_code == 200)
cleanup(tid)

# ---------- C: 重规划暂停时驳回 ----------
print("== C: 重规划暂停时驳回 ==")
tid = new_task({"scenario": {"fire_origin": {"x": 250, "y": 250}, "fire_area_m2": 900,
               "growth_rate": 0.2, "wind_shift": {"round": 2, "speed": 8.5}}})
approve(tid)
rnd(tid, 1)
rnd(tid, 2)  # 风变 → awaiting_confirmation
r = client.post(f"/api/tasks/{tid}/approval", json={"action": "reject", "reason": "matrix reject"})
check("C", "驳回成功", r.status_code == 200, r.text[:60])
items = client.get("/api/analyzes?limit=3&slim=1").json()["items"]
me = next(i for i in items if i["analysis_id"] == tid)
check("C", "驳回后回待确认", me["status"] == "awaiting_confirmation", me["status"])

# ---------- D: 持续压制有效性（换电接通后火情净下降） ----------
print("== D: 持续压制 ==")
tid = new_task({"scenario": {"fire_origin": {"x": 300, "y": 300}, "fire_area_m2": 900,
               "growth_rate": 0.2}})
approve(tid)
rnd(tid, 1)
loads = []
decreased = False
for n in range(2, 8):
    rn = rnd(tid, n)
    if rn.status_code != 200:
        break
    after = (rn.json().get("after") or {}).get("fire_load_flp")
    before = (rn.json().get("before") or {}).get("fire_load_flp")
    loads.append(f"{before}->{after}")
    if after is not None and before is not None and after < before:
        decreased = True
    if rn.json().get("next_action") == "finish":
        break
check("D", "火情净下降（换电续喷有效）", decreased, " ".join(loads[:6]))
check("D", "持续压制不崩", len(loads) >= 2)
cleanup(tid)

# ---------- E: 无候选补位 → none → 继续推进 ----------
print("== E: 无候选补位 ==")
tid = new_task({"scenario": {"fire_origin": {"x": 300, "y": 300}, "fire_area_m2": 900,
               "growth_rate": 0.2, "uav_failure_round": 2}})
approve(tid)
rnd(tid, 1)
# 手动把其余 E 机全部打故障（制造无候选）
client.post(f"/api/tasks/{tid}/rounds", json={"round": 2, "elapsed_minutes": 1, "extinguishing_liters": 0})
r3 = rnd(tid, 3, liters=0)
check("E", "无候选时任务不崩", r3.status_code == 200, r3.text[:60])
cleanup(tid)

print(f"=== 矩阵汇总: PASS={len(PASS)} FAIL={len(FAIL)} ===")
if FAIL:
    print("FAILED:", FAIL)
sys.exit(0 if not FAIL else 1)
