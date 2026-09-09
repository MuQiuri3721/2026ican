# -*- coding: utf-8 -*-
"""联网抓取的不同火情真实照片 × VLM 识别套件。

每张统一指定坐标 (32.10, 118.90)（同时复验 operator-gps 定位）+ use_vlm=true。
每张最多 3 次尝试（限流/失败间隔 75s），单张测完立即终止清场释放资源锁。
结果写 e2e/_real_images/webfire/results.json。
用法：python e2e/_webfire_suite.py
"""
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8000"
WEBDIR = Path("e2e/_real_images/webfire")
LAT, LNG = 32.10, 118.90

# (文件, 类别, 目视内容, 预期 fire_presence, 预期 visual_scale 区间)
CASES = [
    ("large_1.jpg", "large", "航拍活火线+大量浓烟", "flame_observed", ["large"]),
    ("large_2.jpg", "large", "大面积过火区+烟带(无明火)", ["flame_observed", "smoke_only"], ["large", "medium"]),
    ("medium_1.jpg", "medium", "黄昏山腰火带+浓烟", "flame_observed", ["medium", "large"]),
    ("medium_2.jpg", "medium", "单树火烧+地面火", "flame_observed", ["small", "medium"]),
    ("small_1.jpg", "small", "黄昏秸秆堆小火", "flame_observed", ["small"]),
    ("small_2.jpg", "small", "贴地草火特写", "flame_observed", ["small", "medium"]),
    ("night_1.jpg", "night", "夜间整坡火线", "flame_observed", ["medium", "large"]),
    ("night_2.jpg", "night", "夜间多火带+烟", "flame_observed", ["medium", "large"]),
    ("smolder_2.jpg", "smolder", "林地地面零星火+烟", "flame_observed", ["small", "medium"]),
    ("nofire_1.jpg", "nofire", "绿色林地航拍", "none_observed", []),
    ("nofire_2.jpg", "nofire", "云雾林地航拍(雾易误判烟)", "none_observed", []),
    ("nofire_3.jpg", "nofire", "热带雨林航拍", "none_observed", []),
]

# 免费档 429 → 后端降级门控冷却 90s；重试间隔必须大于它，否则永远撞快速失败
RETRY_DELAY = 100


def post(path, payload, headers, timeout=300):
    req = urllib.request.Request(BASE + path, data=payload, headers=headers)
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def multipart(fields, files):
    boundary = uuid.uuid4().hex
    chunks = []
    for name, value in fields:
        chunks.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
    for name, filename, data, ctype in files:
        chunks.append((f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; "
                       f"filename=\"{filename}\"\r\nContent-Type: {ctype}\r\n\r\n").encode() + data + b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def terminate(analysis_id):
    try:
        body, ctype = multipart([("action", "terminate"), ("reason", "套件清场"), ("operator_id", "webfire-suite")], [])
        post(f"/api/tasks/{analysis_id}/approval", body, {"Content-Type": ctype}, timeout=60)
    except Exception:
        pass


def analyze_one(filename):
    image = (WEBDIR / filename).read_bytes()
    body, ctype = multipart(
        [("scene_id", "forest-demo-01"), ("use_vlm", "true"),
         ("latitude", str(LAT)), ("longitude", str(LNG)),
         ("environment_mode", "offline"), ("people_status", "unknown")],
        [("file", filename, image, "image/jpeg")],
    )
    t0 = time.time()
    env = post("/api/analyze/upload", body, {"Content-Type": ctype}, timeout=300)
    elapsed = time.time() - t0
    res = env.get("result") or {}
    exp = res.get("vlm_explanation") or {}
    obs = exp.get("fire_observation") or {}
    fa = res.get("fire_assessment") or {}
    scene = res.get("scene") or {}
    plan = res.get("dispatch_plan") or {}
    return {
        "analysis_id": env.get("analysis_id"),
        "elapsed_s": round(elapsed, 1),
        "vlm_mode": exp.get("mode"), "vlm_source": exp.get("source"),
        "degraded_reason": exp.get("degraded_reason"),
        "fire_presence": obs.get("fire_presence"),
        "visual_scale": obs.get("visual_scale"),
        "smoke_density": obs.get("smoke_density"),
        "people": (exp.get("object_clues") or {}).get("people", {}).get("state") if isinstance(exp.get("object_clues"), dict) else None,
        "summary": (exp.get("review") or {}).get("human_summary") or exp.get("summary"),
        "mapped_area_m2": fa.get("fire_area_m2"), "mapped_growth": fa.get("growth_rate"),
        "params_source": fa.get("fire_params_source"), "params_scale": fa.get("fire_params_scale"),
        "level": fa.get("level"), "flp": fa.get("fire_load_flp"),
        "drones": len(plan.get("selected_uavs") or []),
        "fire_origin_source": scene.get("fire_origin_source"),
        "fire_origin_gps": scene.get("fire_origin_gps"),
    }


def pre_clean():
    try:
        items = json.load(urllib.request.urlopen(BASE + "/api/analyzes?limit=50", timeout=30))
        rows = items.get("items") or items.get("analyzes") or items if isinstance(items, list) else items.get("items", [])
        for row in rows:
            aid = row.get("analysis_id") or row.get("id")
            status = row.get("status")
            if aid and status in ("awaiting_confirmation", "executing", "approved", "replanning"):
                terminate(aid)
    except Exception:
        pass


def main():
    pre_clean()
    # 断点续跑：已有真实识别(mode=real)的结果不重跑（省限流窗口配额）
    previous = {}
    results_path = WEBDIR / "results.json"
    if results_path.exists():
        try:
            for row in json.loads(results_path.read_text(encoding="utf-8")):
                if row.get("vlm_mode") == "real":
                    previous[row["file"]] = row
        except Exception:
            pass
    results = []
    for filename, category, visual, expect_presence, expect_scales in CASES:
        if filename in previous:
            print(f"\n===== {filename} 已有真实结果, 跳过 =====", flush=True)
            results.append(previous[filename])
            continue
        print(f"\n===== {filename} ({category} · {visual}) =====", flush=True)
        record = None
        for attempt in range(1, 5):
            try:
                candidate = analyze_one(filename)
                if candidate.get("analysis_id"):
                    terminate(candidate["analysis_id"])  # 无论真假识别都立即清场释放锁
                # mode=real 才算拿到真实识别；降级(fallback)视为软失败继续等窗口
                if candidate.get("vlm_mode") == "real":
                    record = candidate
                    break
                print(f"  尝试{attempt}: 降级({candidate.get('degraded_reason') or 'rate-limited'})"
                      f" {candidate.get('elapsed_s')}s", flush=True)
            except urllib.error.HTTPError as error:
                detail = error.read().decode("utf-8", "replace")[:120]
                print(f"  尝试{attempt}: HTTP {error.code} {detail}", flush=True)
            except Exception as error:
                print(f"  尝试{attempt}: {type(error).__name__} {str(error)[:120]}", flush=True)
            if attempt < 4:
                print(f"  {RETRY_DELAY}s 后重试…", flush=True)
                time.sleep(RETRY_DELAY)
        if record:
            record.update({"file": filename, "category": category, "scene_visual": visual,
                           "expect_presence": expect_presence, "expect_scales": expect_scales})
            presence = record.get("fire_presence")
            expected = expect_presence if isinstance(expect_presence, list) else [expect_presence]
            presence_ok = presence in expected
            scale_ok = (not expect_scales) or record.get("visual_scale") in expect_scales
            record["verdict"] = "PASS" if (presence_ok and scale_ok) else "MISMATCH"
            print(f"  mode={record.get('vlm_mode')} 判火={record.get('fire_presence')}"
                  f" 规模={record.get('visual_scale')} 烟={record.get('smoke_density')}"
                  f" → {record.get('mapped_area_m2')}m²@{record.get('mapped_growth')}"
                  f" [{record.get('params_source')}] {record['verdict']} ({record.get('elapsed_s')}s)", flush=True)
            if record.get("analysis_id"):
                terminate(record["analysis_id"])
        else:
            record = {"file": filename, "category": category, "scene_visual": visual,
                      "expect_presence": expect_presence, "expect_scales": expect_scales,
                      "verdict": "UNAVAILABLE(4次尝试均失败)"}
            print("  ❌ 四次尝试均失败", flush=True)
        results.append(record)
        (WEBDIR / "results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
        time.sleep(3)
    ok = sum(1 for r in results if r.get("verdict") == "PASS")
    print(f"\n===== 汇总: {ok}/{len(results)} 符合预期 =====")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
