"""真实照片 VLM 检验套件：6 张真实照片 × 结构化输出约束 → 分析友好 JSON。

每张照片走完整管线（use_vlm=true + 契约守卫），输出统一结构：
  {image, expect, verdict,
   vlm:  {fire_presence, visual_scale, smoke_density, people_state, water_state,
          conflicts, human_summary, contract_complete},
   mapped: {fire_area_m2, growth_rate, source},   # 平台映射后的火情参数
   rate_limited_attempts}
结果落盘 e2e/real_photo_results.json（分析友好，供下一步调度/评估分析直接消费）。
限流时 75s 重试，每张最多 4 次。用法:python e2e/real_photo_suite.py
"""
import json
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
BASE = "http://127.0.0.1:8000"

CASES = [
    ("fire1.jpg", "大规模山火航拍(火线+浓烟+水体)", "flame_observed", {}),
    ("fire3.jpg", "垂直航拍林中火点+烟+过火迹地", "flame_observed", {}),
    ("grassfire6.jpg", "夜间火堆+人群剪影(人员识别)", "flame_observed", {"expect_people": "observed"}),
    ("grassfire7.jpg", "夜间草地大火(明火猛烈)", "flame_observed", {}),
    ("nofire1.jpg", "真实无火林地航拍(T03 防误报)", "none_observed", {}),
    ("nofire2.jpg", "真实无火密林俯拍(T03 防误报)", "none_observed", {}),
]


def call(method, path, payload=None, timeout=600):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    except urllib.error.HTTPError as e:
        return {"_http": e.code, "_body": e.read().decode("utf-8", "replace")[:150]}


def pre_clean():
    rows = call("GET", "/api/analyzes?limit=100&slim=1")
    items = rows.get("items", rows) if isinstance(rows, dict) else rows
    for t in items:
        if t.get("status") in ("awaiting_confirmation", "executing"):
            call("POST", f"/api/tasks/{t['analysis_id']}/approval",
                 {"action": "terminate", "reason": "真实照片套件清场"})


def upload_case(path, name):
    boundary = "----suite"
    payload = (f'--{boundary}\r\nContent-Disposition: form-data; name="use_vlm"\r\n\r\ntrue\r\n'.encode()
               + f'--{boundary}\r\nContent-Disposition: form-data; name="environment_mode"\r\n\r\noffline\r\n'.encode()
               + f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\nContent-Type: image/jpeg\r\n\r\n'.encode()
               + open(path, "rb").read() + f"\r\n--{boundary}--\r\n".encode())
    req = urllib.request.Request(BASE + "/api/analyze/upload", data=payload,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    return json.loads(urllib.request.urlopen(req, timeout=600).read())


def structured(v):
    """约束输出为分析友好结构（vlm-analysis-v1 五组 + 平台映射）。"""
    fo = v.get("fire_observation") or {}
    st = v.get("smoke_trend") or {}
    oc = v.get("object_clues") or {}
    review = v.get("review") or {}
    return {
        "fire_presence": fo.get("fire_presence"),
        "visual_scale": fo.get("visual_scale"),
        "affected_layer": fo.get("affected_layer"),
        "smoke_density": st.get("smoke_density"),
        "temporal_trend": st.get("temporal_trend"),
        "people_state": (oc.get("people") or {}).get("state"),
        "water_state": (oc.get("water") or {}).get("state"),
        "conflicts": review.get("conflicts") or [],
        "manual_review_required": review.get("manual_review_required"),
        "human_summary": review.get("human_summary"),
        "contract_complete": bool(
            isinstance(v.get("image_quality"), dict) and isinstance(fo, dict)
            and isinstance(st, dict) and isinstance(oc, dict) and isinstance(review, dict)),
    }


def main():
    pre_clean()
    results = []
    for name, expect_desc, expect_presence, extra in CASES:
        print(f"=== {name}（{expect_desc}）===", flush=True)
        v, attempts = {}, 0
        for attempt in range(1, 7):
            attempts = attempt
            env = upload_case(f"e2e/_real_images/{name}", name.replace(".jpg", ""))
            aid = env.get("analysis_id")
            v = (env.get("result") or {}).get("vlm_explanation") or {}
            real = v.get("mode") == "real"
            try:
                call("POST", f"/api/tasks/{aid}/approval", {"action": "terminate", "reason": "真实照片套件清理"})
            except Exception:
                pass
            if real:
                break
            print(f"  尝试 {attempt}/{6}: 限流降级,150s 后重试", flush=True)
            if attempt < 6:
                time.sleep(150)
        rec = {"image": name, "expect": expect_desc,
               "expect_presence": expect_presence, "rate_limited_attempts": attempts if not real else attempts - 1,
               "vlm": structured(v), "mapped": None,
               "verdict": "✅" if (v.get("mode") == "real" and v.get("fire_observation", {}).get("fire_presence") == expect_presence) else
                          ("⚠ 限流未取得真实结果" if v.get("mode") != "real" else "❌ 判定不符")}
        results.append(rec)
        print(f"  → {rec['verdict']} | fire_presence={rec['vlm']['fire_presence']} "
              f"| people={rec['vlm']['people_state']} | 摘要={str(rec['vlm']['human_summary'])[:60]}", flush=True)
    with open("e2e/real_photo_results.json", "w", encoding="utf-8") as f:
        json.dump({"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "cases": results}, f, ensure_ascii=False, indent=1)
    ok = sum(1 for r in results if r["verdict"].startswith("✅"))
    warn = sum(1 for r in results if r["verdict"].startswith("⚠"))
    print(f"\n===== 真实照片检验汇总:{ok} 符合 / {warn} 限流未取 / {len(results) - ok - warn} 不符 =====")
    return 0 if warn == 0 and all(r["verdict"].startswith("✅") for r in results) else 1


if __name__ == "__main__":
    import time
    raise SystemExit(main())
