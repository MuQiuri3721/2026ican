"""对照实验：同一固定地点，不同真实程度/规模的图片 → 火情随图变。

- small-fire.jpg（合成小火图）→ VLM 判 small → 600 m² → 低等级
- fire1.jpg（真实大规模山火航拍）→ VLM 判 large → 4500 m² → 高等级大火
限流时段自动重试（每张最多 4 次，间隔 75s）。用法:python e2e/_fire_mapping_test.py
"""
import json
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
BASE = "http://127.0.0.1:8000"


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
    n = 0
    for t in items:
        if t.get("status") in ("awaiting_confirmation", "executing"):
            call("POST", f"/api/tasks/{t['analysis_id']}/approval",
                 {"action": "terminate", "reason": "对照实验前置清场"})
            n += 1
    if n:
        print(f"前置清场 {n} 个在途任务", flush=True)
        time.sleep(1)


def upload_until_real(path, name, attempts=4):
    for attempt in range(1, attempts + 1):
        boundary = "----maptest"
        payload = (f'--{boundary}\r\nContent-Disposition: form-data; name="use_vlm"\r\n\r\ntrue\r\n'.encode()
                   + f'--{boundary}\r\nContent-Disposition: form-data; name="environment_mode"\r\n\r\noffline\r\n'.encode()
                   + f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\nContent-Type: image/jpeg\r\n\r\n'.encode()
                   + open(path, "rb").read() + f"\r\n--{boundary}--\r\n".encode())
        req = urllib.request.Request(BASE + "/api/analyze/upload", data=payload,
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        env = json.loads(urllib.request.urlopen(req, timeout=600).read())
        aid = env.get("analysis_id")
        r = env.get("result") or {}
        v = r.get("vlm_explanation") or {}
        fa = r.get("fire_assessment") or {}
        try:
            call("POST", f"/api/tasks/{aid}/approval", {"action": "terminate", "reason": "对照实验清理"})
        except Exception:
            pass
        if v.get("mode") == "real":
            return v, fa
        print(f"  [{name}] 尝试 {attempt}/{attempts}: 限流降级", flush=True)
        if attempt < attempts:
            time.sleep(75)
    return v, fa


CASES = (("small-fire.jpg", "合成小火"), ("fire1.jpg", "真实大规模山火"))
ok_count = 0
pre_clean()
for name, label in CASES:
    path = f"e2e/{name}" if name == "small-fire.jpg" else f"e2e/_real_images/{name}"
    print(f"=== {label}({name}) ===", flush=True)
    v, fa = upload_until_real(path, name)
    scale = ((v.get("fire_observation") or {}).get("visual_scale")) if v.get("mode") == "real" else "降级"
    print(f"  mode={v.get('mode')} | visual_scale={scale} | 面积={fa.get('fire_area_m2')} m² "
          f"| FLP={( None, fa.get('fire_load_flp'))[1]} | 等级={fa.get('label')} "
          f"| 来源={fa.get('fire_params_source')}", flush=True)
    if v.get("mode") == "real":
        ok_count += 1

print(f"\n===== 对照完成:真实识别成功 {ok_count}/2 =====")
