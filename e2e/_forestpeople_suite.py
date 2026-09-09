# -*- coding: utf-8 -*-
"""森林场景 × 人员距离矩阵 VLM 识别套件。

核心考察：object_clues.people.state（人员识别驱动疏散分支）随拍摄距离的表现，
同时复核 fire_presence 判定。统一指定坐标 (32.10, 118.90)。
仅 mode=real 算成功；重试间隔 100s（>降级冷却 90s）；每张测完立即清场。
结果写 e2e/_real_images/forestpeople/results.json。
用法：python e2e/_forestpeople_suite.py
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
WEBDIR = Path("e2e/_real_images/forestpeople")
LAT, LNG = 32.10, 118.90
RETRY_DELAY = 100

# (文件, 场景说明, 预期 fire_presence, 预期 people.state)
CASES = [
    ("forest_far_1.jpg", "无火森林 远景航拍", "none_observed", "not_observed"),
    ("forest_far_2.jpg", "无火森林 远景", "none_observed", "not_observed"),
    ("forest_far_3.jpg", "无火森林 远景", "none_observed", "not_observed"),
    ("forest_near_1.jpg", "无火森林 林间小路 近景", "none_observed", "not_observed"),
    ("forest_near_2.jpg", "无火森林 近景", "none_observed", "not_observed"),
    ("forest_near_3.jpg", "无火森林 近景", "none_observed", "not_observed"),
    ("fire_far_1.jpg", "森林火情 远景航拍(林间火点+烟)", "flame_observed", "not_observed"),
    ("fire_far_2.jpg", "森林火情 远景", "flame_observed", "not_observed"),
    ("fire_far_3.jpg", "森林火情 远景", "flame_observed", "not_observed"),
    ("fire_near_1.jpg", "森林地面火 近景(树干+火焰)", "flame_observed", "not_observed"),
    ("fire_near_2.jpg", "林地余火+烟 近景", "flame_observed", "not_observed"),
    ("firefighter_1.jpg", "森林消防员近景+背景火线", "flame_observed", "observed"),
    ("firefighter_2.jpg", "消防员喷水灭火 人+火", "flame_observed", "observed"),
    ("firefighter_3.jpg", "两名消防员 燃烧林地", "flame_observed", "observed"),
    ("people_far_1.jpg", "徒步队伍 人占画面大(近景)", "none_observed", "observed"),
    ("people_far_2.jpg", "林中徒步 近景", "none_observed", "observed"),
    ("people_far_3.jpg", "四人林间小路 中景", "none_observed", "observed"),
    ("people_near_1.jpg", "逆光剪影 单人 中景", "none_observed", "observed"),
    ("people_near_2.jpg", "单人 大近景", "none_observed", "observed"),
    ("people_near_3.jpg", "单人 中景", "none_observed", "observed"),
    ("people_tiny_1.jpg", "航拍 人不可辨 极远", "none_observed", "not_observed"),
    ("people_tiny_2.jpg", "航拍 人不可辨 极远", "none_observed", "not_observed"),
    ("people_tiny_3.jpg", "航拍 人不可辨 极远", "none_observed", "not_observed"),
]


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
        body = json.dumps({"action": "terminate", "reason": "套件清场"}).encode()
        post(f"/api/tasks/{analysis_id}/approval", body, {"Content-Type": "application/json"}, timeout=60)
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
    clues = exp.get("object_clues") or {}
    people = clues.get("people") or {}
    fa = res.get("fire_assessment") or {}
    return {
        "analysis_id": env.get("analysis_id"),
        "elapsed_s": round(elapsed, 1),
        "vlm_mode": exp.get("mode"), "vlm_source": exp.get("source"),
        "fire_presence": obs.get("fire_presence"),
        "visual_scale": obs.get("visual_scale"),
        "people_state": people.get("state"),
        "people_evidence": people.get("evidence"),
        "summary": (exp.get("review") or {}).get("human_summary") or exp.get("summary"),
        "mapped_area_m2": fa.get("fire_area_m2"), "mapped_growth": fa.get("growth_rate"),
        "params_source": fa.get("fire_params_source"),
        "fire_origin_source": (res.get("scene") or {}).get("fire_origin_source"),
    }


def pre_clean():
    try:
        items = json.load(urllib.request.urlopen(BASE + "/api/analyzes?limit=50", timeout=30))
        rows = items.get("items") or items if isinstance(items, list) else items.get("items", [])
        for row in rows:
            aid = row.get("analysis_id") or row.get("id")
            if aid and row.get("status") in ("awaiting_confirmation", "executing", "approved", "replanning"):
                terminate(aid)
    except Exception:
        pass


def main():
    pre_clean()
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
    for filename, visual, expect_fire, expect_people in CASES:
        if filename in previous:
            print(f"===== {filename} 已有真实结果, 跳过 =====", flush=True)
            results.append(previous[filename])
            continue
        print(f"===== {filename} ({visual} · 期望火={expect_fire} 人={expect_people}) =====", flush=True)
        record = None
        for attempt in range(1, 5):
            try:
                candidate = analyze_one(filename)
                if candidate.get("analysis_id"):
                    terminate(candidate["analysis_id"])
                if candidate.get("vlm_mode") == "real":
                    record = candidate
                    break
                print(f"  尝试{attempt}: 降级({candidate.get('vlm_mode')})", flush=True)
            except urllib.error.HTTPError as error:
                print(f"  尝试{attempt}: HTTP {error.code}", flush=True)
            except Exception as error:
                print(f"  尝试{attempt}: {type(error).__name__} {str(error)[:100]}", flush=True)
            if attempt < 4:
                print(f"  {RETRY_DELAY}s 后重试…", flush=True)
                time.sleep(RETRY_DELAY)
        if record:
            record.update({"file": filename, "scene": visual,
                           "expect_fire": expect_fire, "expect_people": expect_people})
            fire_ok = record.get("fire_presence") == expect_fire
            people_ok = record.get("people_state") == expect_people
            record["verdict"] = "PASS" if (fire_ok and people_ok) else (
                "FIRE-MISMATCH" if not fire_ok else "PEOPLE-MISMATCH")
            print(f"  火={record.get('fire_presence')} 人={record.get('people_state')}"
                  f" → {record.get('mapped_area_m2')}m²@{record.get('mapped_growth')}"
                  f" [{record['verdict']}] ({record.get('elapsed_s')}s)", flush=True)
        else:
            record = {"file": filename, "scene": visual, "expect_fire": expect_fire,
                      "expect_people": expect_people, "verdict": "UNAVAILABLE"}
            print("  ❌ 四次尝试均失败", flush=True)
        results.append(record)
        (WEBDIR / "results.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
        time.sleep(3)
    ok = sum(1 for r in results if r.get("verdict") == "PASS")
    print(f"\n===== 汇总: {ok}/{len(results)} 全符合 =====")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
