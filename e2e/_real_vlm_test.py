"""真实照片 VLM 检验：三张真实照片（非合成）逐张过 glm-4.6v-flash。

- fire1.jpg  大规模山火航拍（火线+浓烟）→ 应识别火焰
- fire3.jpg  垂直航拍林中火点+烟+过火迹地 → 应识别火焰
- nofire1.jpg 真实无火林地航拍 → 不得报火焰（交付 T03 防误报口径）

限流时 75s 重试，每张最多 3 次。用法:python e2e/_real_vlm_test.py
"""
import json
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")


def call(method, path, payload=None, timeout=600):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request("http://127.0.0.1:8000" + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    except urllib.error.HTTPError as e:
        return {"_http": e.code, "_body": e.read().decode("utf-8", "replace")[:150]}


def vlm_check(filename):
    boundary = "----real"
    payload = (f'--{boundary}\r\nContent-Disposition: form-data; name="use_vlm"\r\n\r\ntrue\r\n'.encode()
               + f'--{boundary}\r\nContent-Disposition: form-data; name="environment_mode"\r\n\r\noffline\r\n'.encode()
               + f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: image/jpeg\r\n\r\n'.encode()
               + open(f"e2e/_real_images/{filename}", "rb").read() + f"\r\n--{boundary}--\r\n".encode())
    req = urllib.request.Request("http://127.0.0.1:8000/api/analyze/upload", data=payload,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    env = json.loads(urllib.request.urlopen(req, timeout=600).read())
    aid = env.get("analysis_id")
    v = (env.get("result") or {}).get("vlm_explanation") or {}
    real = v.get("mode") == "real"
    fo = v.get("fire_observation") or {}
    conflicts = (v.get("review") or {}).get("conflicts") or []
    summary = (v.get("review") or {}).get("human_summary") or ""
    try:
        call("POST", f"/api/tasks/{aid}/approval", {"action": "terminate", "reason": "真实图检验清理"})
    except Exception:
        pass
    return real, fo, conflicts, summary


CASES = (("fire1.jpg", "大规模山火:火线+浓烟", "flame_observed"),
         ("fire3.jpg", "林中火点+烟+过火迹地", "flame_observed"),
         ("nofire1.jpg", "无火绿色林地(T03 防误报)", "none_observed"))

ok_count = 0
total = 0
for name, expect_desc, expect_presence in CASES:
    print(f"=== {name}({expect_desc}) ===", flush=True)
    got = None
    for attempt in range(1, 4):
        real, fo, conflicts, summary = vlm_check(name)
        if not real:
            print(f"  尝试 {attempt}: 限流降级,75s 后重试", flush=True)
            time.sleep(75)
            continue
        got = fo.get("fire_presence")
        conflicts_txt = "; ".join(str(c) for c in conflicts)[:90] if conflicts else "无"
        print(f"  fire_presence={got} | 冲突上报: {conflicts_txt}", flush=True)
        print(f"  摘要: {summary[:90]}", flush=True)
        break
    total += 1
    verdict = (got == expect_presence)
    ok_count += verdict
    print(f"  判定: {'✅ 符合预期' if verdict else '❌ 不符(期望 ' + expect_presence + ')'}", flush=True)
print(f"\n===== 真实照片检验汇总:{ok_count}/{total} 符合预期 =====")
