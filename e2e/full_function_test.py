"""全功能逐项测试（纯 API）：一条命令过一遍后端全部对外功能，输出分组报告。

UI 层由 e2e/round1-15 与 acceptance_six 覆盖；本文件负责功能清单式确认：
平台基础 / 环境 / 知识库 / 影像接入（单图·多图·视频·大火） / VLM / 任务闭环
（批准·推演·失能补位·风变重规划·结案回收·驳回·终止） / 消息流 / 报告 / 问答 / 历史 / 健壮性。

用法:python e2e/full_function_test.py   退出码 0=全部必过项通过
"""
import io
import json
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8000"

PASS, WARN, FAIL = [], [], []


def call(method, path, payload=None, timeout=180, raw=False):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            return resp.status, (body if raw else json.loads(body))
    except urllib.error.HTTPError as error:
        raw = error.read()[:300]
        try:
            return error.code, json.loads(raw)
        except Exception:
            return error.code, raw.decode("utf-8", "replace")


def record(group, name, ok, detail="", warn=False, soft=False):
    """soft=True:失败只记警告（可选能力，如 TTS/知识库在离线环境）。"""
    if ok:
        (WARN if warn else PASS).append(f"{group}/{name}")
        mark = "⚠" if warn else "✅"
    else:
        (WARN if soft else FAIL).append(f"{group}/{name}")
        mark = "⚠" if soft else "❌"
    print(f"{mark} [{group}] {name}" + (f" | {detail}" if detail else ""))


def pre_clean():
    """终止历史遗留的待确认/执行中任务,释放资源锁（同 acceptance_six 前置清场）。"""
    code, rows = call("GET", "/api/analyzes?limit=100&slim=1")
    items = rows.get("items", rows) if isinstance(rows, dict) else rows
    for t in items:
        if t.get("status") in ("awaiting_confirmation", "executing"):
            call("POST", f"/api/tasks/{t['analysis_id']}/approval", {"action": "terminate", "reason": "全功能测试前置清场"})


def upload_image(filename, use_vlm="false"):
    boundary = "----fullfunctest"
    data = (f'--{boundary}\r\nContent-Disposition: form-data; name="use_vlm"\r\n\r\n{use_vlm}\r\n'.encode()
            + f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: image/jpeg\r\n\r\n'.encode()
            + Path(ROOT / "e2e" / filename).read_bytes() + f"\r\n--{boundary}--\r\n".encode())
    req = urllib.request.Request(BASE + "/api/analyze/upload", data=data,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read())


def terminate(aid):
    call("POST", f"/api/tasks/{aid}/approval", {"action": "terminate", "reason": "全功能测试清理"})


pre_clean()
time.sleep(1)

# ---------- A. 平台基础 ----------
print("== A. 平台基础 ==")
code, health = call("GET", "/api/health")
record("A", "health", code == 200 and health.get("status") == "ok")
code, status = call("GET", "/api/project-status")
record("A", "project-status 接入徽标", code == 200 and {"yolo", "vlm"} <= set(status),
       f"yolo={status.get('yolo')} vlm={status.get('vlm')}")
code, llm = call("GET", "/api/llm-status")
record("A", "llm-status", code == 200 and "available" in llm, f"mode={llm.get('mode')}")
code, fleet = call("GET", "/api/fleet")
fleet_count = len(fleet.get("fleet", fleet)) if isinstance(fleet, dict) else 0
record("A", "机群 2R+4E+2S", fleet_count == 8, f"count={fleet_count}")
code, inv = call("GET", "/api/inventory")
record("A", "库存", code == 200 and isinstance(inv, dict) and "water_liters" in json.dumps(inv))
code, tools = call("GET", "/api/tools")
tool_count = len(tools.get("tools", tools)) if isinstance(tools, (dict, list)) else 0
record("A", "tools 注册表", tool_count >= 53, f"count={tool_count}")
code, skills = call("GET", "/api/skills")
skill_count = len(skills.get("skills", skills)) if isinstance(skills, (dict, list)) else 0
record("A", "skills 注册表", skill_count >= 15, f"count={skill_count}")
code, grid = call("GET", "/api/terrain/grid?latitude=32.0725&longitude=118.8415&radius_deg=0.04&size=64")
record("A", "三维地形网格(DEM 高程)", code == 200 and (grid.get("max_elev") or 0) > 100, f"elevations={len(grid.get('elevations') or [])} max={grid.get('max_elev')}m", soft=True)

# ---------- B. 环境 ----------
print("== B. 环境服务 ==")
code, env = call("GET", "/api/environment?scene_id=forest-demo-01&latitude=32.0725&longitude=118.8415", timeout=240)
has_water = "water" in json.dumps(env, ensure_ascii=False).lower() or env.get("sources")
record("B", "环境加载(水源/道路/气象)", code == 200 and bool(has_water))

# ---------- C. 知识库 ----------
print("== C. 经验知识库 ==")
code, kb = call("GET", "/api/knowledge?query=" + urllib.parse.quote("火灾 处置") + "&top_k=2")
record("C", "知识库检索", code == 200 and bool(kb.get("results") or kb.get("matched")), soft=True,
       detail=json.dumps(kb, ensure_ascii=False)[:60])

# ---------- D. 影像接入与检测 ----------
print("== D. 影像接入与检测 ==")
env0 = upload_image("fire.jpg")
r0 = env0.get("result") or {}
record("D", "单图上传→研判完成", env0.get("status") in ("awaiting_confirmation", "completed")
       and bool(r0.get("dispatch_plan")), f"FLP={(r0.get('dispatch_plan') or {}).get('fire_load_flp')}")
terminate(env0.get("analysis_id"))

env_multi = None
boundary = "----multi"
parts = b"".join(
    f'--{boundary}\r\nContent-Disposition: form-data; name="frames"; filename="f{i}.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'.encode()
    + Path(ROOT / "e2e" / name).read_bytes() + b"\r\n"
    for i, name in enumerate(("fire2.jpg", "small-fire.jpg"), 1))
parts += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="main.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'.encode()
          + Path(ROOT / "e2e" / "fire.jpg").read_bytes() + f"\r\n--{boundary}--\r\n".encode())
req = urllib.request.Request(BASE + "/api/analyze/upload", data=parts,
                             headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
with urllib.request.urlopen(req, timeout=300) as resp:
    env_multi = json.loads(resp.read())
multi_result = env_multi.get("result") or {}
seq = (multi_result.get("visual_sequence") or [])
record("D", "多图序列(3 帧)", env_multi.get("status") in ("awaiting_confirmation", "completed") and len(seq) >= 2,
       f"visual_sequence={len(seq)}")
terminate(env_multi.get("analysis_id"))

import cv2
import numpy as np
tmp_mp4 = Path(tempfile.mkdtemp(prefix="fft-")) / "test.mp4"
writer = cv2.VideoWriter(str(tmp_mp4), cv2.VideoWriter_fourcc(*"mp4v"), 10, (320, 240))
for i in range(40):
    writer.write(np.full((240, 320, 3), 30 + i * 5, dtype=np.uint8))
writer.release()
boundary = "----vid"
vid_data = (f'--{boundary}\r\nContent-Disposition: form-data; name="use_vlm"\r\n\r\nfalse\r\n'.encode()
            + f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="clip.mp4"\r\nContent-Type: video/mp4\r\n\r\n'.encode()
            + tmp_mp4.read_bytes() + f"\r\n--{boundary}--\r\n".encode())
req = urllib.request.Request(BASE + "/api/analyze/upload", data=vid_data,
                             headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
with urllib.request.urlopen(req, timeout=300) as resp:
    env_vid = json.loads(resp.read())
vid_obs = (((env_vid.get("result") or {}).get("agent") or {}).get("skill_chain") or {}).get("fire_perception", {}).get("observation", {})
record("D", "视频上传→自动抽帧", env_vid.get("status") in ("awaiting_confirmation", "completed"),
       f"image={Path((env_vid.get('input') or {}).get('image_path') or 'x').name}")
terminate(env_vid.get("analysis_id"))

env_big = upload_image("large-fire.jpg")
big_plan = (env_big.get("result") or {}).get("dispatch_plan") or {}
record("D", "large-fire 不可控口径", big_plan.get("can_control") is False and (big_plan.get("fire_load_flp") or 0) > 3000,
       f"FLP={big_plan.get('fire_load_flp')} can_control={big_plan.get('can_control')}")
terminate(env_big.get("analysis_id"))

code, _ = call("POST", "/api/analyze/upload", {"x": 1})
record("D", "非法上传被拒", code in (415, 422))

# ---------- E. VLM ----------
print("== E. VLM 视觉解释 ==")
env_vlm = upload_image("fire.jpg", use_vlm="true")
v = (env_vlm.get("result") or {}).get("vlm_explanation") or {}
if v.get("mode") == "real":
    record("E", "VLM 真实解释", True, f"source={v.get('source')} 摘要={len(v.get('summary') or '')}字")
elif v.get("mode") == "fallback":
    record("E", "VLM 限流降级路径", True, f"code={(v.get('adapter_fallback') or {}).get('code')}（免费档限流窗口，降级即正确行为）", warn=True)
else:
    record("E", "VLM 解释", False, json.dumps(v, ensure_ascii=False)[:100])
terminate(env_vlm.get("analysis_id"))

# ---------- F. 任务闭环（演训场景驱动） ----------
print("== F. 任务闭环 ==")

def crossing_wind_shift(base_wind):
    """按实时风所在档取一个必然异档的 shift 速度（FE-35：必须真跨档才触发）。"""
    band = 0 if base_wind < 4 else 1 if base_wind < 6 else 2 if base_wind < 8 else 3
    return 10.0 if band <= 2 else 2.0


def run_mission(label, scenario, expect_replan=False):
    body = {"scene_id": "forest-demo-01", "image_name": "scenario", "people_status": "unknown", "scenario": scenario}
    code, envelope = call("POST", "/api/analyze", body)
    aid = envelope.get("analysis_id")
    if envelope.get("status") != "awaiting_confirmation":
        record("F", label + "·待确认", False, json.dumps(envelope, ensure_ascii=False)[:120])
        return None
    record("F", label + "·待确认+审批门", True, f"FLP={((envelope.get('result') or {}).get('dispatch_plan') or {}).get('fire_load_flp')}")
    code, approved = call("POST", f"/api/tasks/{aid}/approval", {"action": "approve", "reason": "全功能测试"})
    approved = approved if isinstance(approved, dict) else {}
    if code != 200 and "锁定" in str(approved):
        holder = str(approved).split("锁定：")[-1].split("（")[0].strip()
        call("POST", f"/api/tasks/{holder}/approval", {"action": "terminate", "reason": "全功能测试:释放僵尸锁"})
        time.sleep(1.5)
        code, approved = call("POST", f"/api/tasks/{aid}/approval", {"action": "approve", "reason": "全功能测试"})
        approved = approved if isinstance(approved, dict) else {}
    record("F", label + "·批准执行", code == 200 and approved.get("status") in ("executing", "completed", "monitoring"),
           f"status={approved.get('status')} {'' if code == 200 else approved}")
    if code != 200:
        return None
    versions, finished, events = 1, False, []
    status, last_detail = None, ""
    _, current = call("GET", f"/api/analyze/{aid}")
    current = current if isinstance(current, dict) else {}
    round_start = int(current.get("monitor_round") if current.get("monitor_round") is not None else 0) + 1
    round_no = round_start - 1
    re_approvals = 0
    round_no = round_start - 1
    while round_no < round_start + 20:
        round_no += 1
        code, round_resp = call("POST", f"/api/tasks/{aid}/rounds",
                                {"round": round_no, "elapsed_minutes": 5, "extinguishing_liters": 0})
        if code == 409 and "尚未批准" in str(round_resp) and re_approvals < 4:
            # 重规划触发 → 任务回待确认等 v2 审批（FE-39 设计）：再批准后继续推演
            code2, _re = call("POST", f"/api/tasks/{aid}/approval", {"action": "approve", "reason": "全功能测试:重规划再审批"})
            if code2 == 200:
                re_approvals += 1
                round_no -= 1
                continue
        if code != 200:
            last_detail = f"round{round_no} HTTP{code}: {round_resp if isinstance(round_resp, str) else json.dumps(round_resp, ensure_ascii=False)[:120]}"
            break
        events = round_resp.get("events") or events
        new_versions = len(round_resp.get("plan_versions") or []) if isinstance(round_resp, dict) else 0
        if new_versions > versions:
            versions = new_versions
        _, env_now = call("GET", f"/api/analyze/{aid}")
        status = env_now.get("status") if isinstance(env_now, dict) else None
        if round_resp.get("action") == "finish" or status == "completed":
            finished = True
            break
    ok_rounds = finished or (round_no >= round_start + 2)
    record("F", label + "·推演轮次推进", ok_rounds, f"轮数={round_no} status={status} {last_detail}")
    if not finished:
        terminate(aid)  # 未扑灭也自清理,不留占锁任务
    _, env_final = call("GET", f"/api/analyze/{aid}")
    env_final = env_final if isinstance(env_final, dict) else {}
    versions = len(env_final.get("plan_versions") or [])
    rounds_log = json.dumps(env_final.get("rounds") or [], ensure_ascii=False)
    if expect_replan:
        wind_hit = "wind_band_changed" in rounds_log
        record("F", label + "·风变跨档触发重规划", wind_hit and versions >= 2,
               f"plan_versions={versions} 再审批={re_approvals} wind_band_changed={wind_hit}")
    code, report = call("GET", f"/api/tasks/{aid}/report")
    record("F", label + "·报告生成", code == 200 and bool(report))
    code, messages = call("GET", f"/api/tasks/{aid}/agent-messages")
    msg_text = json.dumps(messages, ensure_ascii=False)
    record("F", label + "·Agent 黑板消息", code == 200 and len(msg_text) > 50)
    code, sse = call("GET", f"/api/tasks/{aid}/events/stream?once=1", timeout=30, raw=True)
    record("F", label + "·SSE 事件流(once)", code == 200 and b"event:" in sse)
    if finished:
        code, msgs = call("GET", f"/api/tasks/{aid}/agent-messages")
        msg_types = [m.get("msg_type") for m in ((msgs or {}).get("items") or []) if isinstance(m, dict)]
        record("F", label + "·结案回收 RECOVERY 消息", "RECOVERY" in msg_types, f"尾部消息={msg_types[-6:]}")
    return aid

aid_a = run_mission("失能演练", {"fire_origin": {"x": 100, "y": -200}, "fire_area_m2": 300,
                                "growth_rate": 0.1, "uav_failure_round": 2})
fault_hit = False
if aid_a:
    code, messages = call("GET", f"/api/tasks/{aid_a}/agent-messages")
    msg_text = json.dumps(messages, ensure_ascii=False)
    fault_hit = ("UAV_FAULT" in msg_text) and ("BACKFILL" in msg_text)
record("F", "失能→故障+补位消息", fault_hit)
if aid_a:
    code, full_msgs = call("GET", f"/api/tasks/{aid_a}/agent-messages")
    msg_types = [m.get("msg_type") for m in ((full_msgs or {}).get("items") or []) if isinstance(m, dict)]
    record("F", "结案回收 RECOVERY 消息", "RECOVERY" in msg_types, f"类型序列={msg_types}")
    code, chat = call("POST", f"/api/tasks/{aid_a}/chat", {"question": "水剂还剩多少？"})
    record("F", "指挥员问答接地", code == 200 and any(ch.isdigit() for ch in json.dumps(chat, ensure_ascii=False)),
           json.dumps(chat, ensure_ascii=False)[:60])

_, _env_now = call("GET", "/api/environment?scene_id=forest-demo-01&latitude=32.0725&longitude=118.8415", timeout=240)
_base_wind = float((_env_now or {}).get("wind_speed") or 3.0)

def run_wind_mission(speed, tag):
    aid = run_mission("风变演练(" + tag + ")", {"fire_origin": {"x": 150, "y": -150}, "fire_area_m2": 2000,
                      "growth_rate": 0.5, "wind_shift": {"round": 2, "speed": speed}})
    _, env_final = call("GET", f"/api/analyze/{aid}")
    env_final = env_final if isinstance(env_final, dict) else {}
    versions = len(env_final.get("plan_versions") or [])
    wind_hit = "wind_band_changed" in json.dumps(env_final.get("rounds") or [], ensure_ascii=False)
    return aid, wind_hit, versions

_first_speed = crossing_wind_shift(_base_wind)
aid_b, wind_hit, pv = run_wind_mission(_first_speed, f"{_first_speed}m/s")
if not (wind_hit and pv >= 2):
    complement = 2.0 if _first_speed == 10.0 else 10.0
    print(f"  ↻ 首选 {_first_speed} m/s 未跨档(基线风与探测不一致),换 {complement} m/s 重跑")
    aid_b, wind_hit, pv = run_wind_mission(complement, f"{complement}m/s")
record("F", "风变→重规划版本", wind_hit and pv >= 2, f"plan_versions={pv} wind_band_changed={wind_hit}")

code, item = call("POST", "/api/analyze", {"scene_id": "forest-demo-01", "image_name": "probe",
                  "scenario": {"fire_origin": {"x": 0, "y": 0}, "fire_area_m2": 2000, "growth_rate": 0.42},
                  "people_status": "unknown"})
aid_c = item.get("analysis_id")
code, rejected = call("POST", f"/api/tasks/{aid_c}/approval", {"action": "reject", "reason": "驳回路径测试"})
record("F", "驳回→回到待确认+释放锁", rejected.get("status") == "awaiting_confirmation")
terminate(aid_c)

# ---------- G. 报告下载与历史 ----------
print("== G. 报告与历史 ==")
if aid_a:
    code, blob = call("GET", f"/api/tasks/{aid_a}/report/download", raw=True)
    record("G", "报告下载", code == 200 and len(blob) > 100)
code, rows = call("GET", "/api/analyzes?limit=5&slim=1")
items = rows.get("items", rows) if isinstance(rows, dict) else rows
record("G", "历史列表 limit+slim", code == 200 and len(items) >= 3, f"rows={len(items)}")

# ---------- H. 健壮性抽样 ----------
print("== H. 健壮性抽样 ==")
code, _ = call("POST", "/api/analyze", {"scene_id": "x", "scenario": {"fire_area_m2": "abc"}})
record("H", "非法 scenario→422", code == 422)
code, _ = call("POST", "/api/tasks/not-exist/chat", {"question": "hi"})
record("H", "未知任务→4xx", 400 <= code < 500)
code, _ = call("POST", f"/api/tasks/{aid_c or 'x'}/rounds", {"round": -3, "elapsed_minutes": 5})
record("H", "非法轮次→4xx", 400 <= code < 500)

# ---------- 汇总 ----------
print(f"\n===== 全功能测试汇总:必过 {len(PASS)} 项通过,警告 {len(WARN)} 项,失败 {len(FAIL)} 项 =====")
if WARN:
    print("⚠ 警告项:")
    for item in WARN:
        print("  -", item)
if FAIL:
    print("❌ 失败项:")
    for item in FAIL:
        print("  -", item)
sys.exit(0 if not FAIL else 1)
