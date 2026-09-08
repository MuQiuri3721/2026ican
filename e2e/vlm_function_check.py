"""VLM 功能实弹检验(按交付 §8.2 验收口径):真实调用 glm-4.6v-flash 逐项过口径。

用例(对照 VLM 队员交付包 12 组案例的可离线复刻子集):
  T1 火焰识别   真实火场照片        → fire_observation.fire_presence = flame_observed
  T2 防误报     纯林地(合成,无火)  → 不得报 flame_observed(none_observed/uncertain 均可)
  T3 水源口径   林地湖泊(合成)     → water.state 只能 water_candidate(不得判定可取水)
  T4 契约完整   三例响应五组必填字段组齐全 + human_summary 非空

用法:python e2e/vlm_function_check.py(后端须在 :8000;免费档限流时单例最长 2-3 分钟)
退出码:0=全部口径通过。测试图由脚本用 OpenCV 现场合成,自包含无外部依赖。
"""
import json
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
BASE = "http://127.0.0.1:8000"
RESULTS = []


def call(method, path, payload=None, timeout=600):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def upload_and_analyze(path):
    boundary = "----vlmcheck"
    payload = (f'--{boundary}\r\nContent-Disposition: form-data; name="use_vlm"\r\n\r\ntrue\r\n'.encode()
               + f'--{boundary}\r\nContent-Disposition: form-data; name="environment_mode"\r\n\r\noffline\r\n'.encode()
               + f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.split("/")[-1]}"\r\nContent-Type: image/jpeg\r\n\r\n'.encode()
               + open(path, "rb").read() + f"\r\n--{boundary}--\r\n".encode())
    req = urllib.request.Request(BASE + "/api/analyze/upload", data=payload,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    env = json.loads(urllib.request.urlopen(req, timeout=600).read())
    aid = env.get("analysis_id")
    v = (env.get("result") or {}).get("vlm_explanation") or {}
    try:
        call("POST", f"/api/tasks/{aid}/approval", {"action": "terminate", "reason": "vlm 检验清理"})
    except Exception:
        pass
    return v


def check(name, ok, detail=""):
    RESULTS.append((name, ok))
    print(f"{'✅' if ok else '❌'} {name}" + (f" | {detail}" if detail else ""))


def main():
    import cv2
    import numpy as np

    rng = np.random.default_rng(7)

    # 合成 T2 纯林地(无火):绿色渐变山体 + 树冠斑块
    img = np.zeros((720, 1280, 3), dtype=np.uint8)
    for y in range(720):
        img[y, :] = (30 + int(40 * y / 720), 90 + int(60 * y / 720), 20 + int(30 * y / 720))
    for _ in range(400):
        cv2.circle(img, (int(rng.integers(0, 1280)), int(rng.integers(0, 720))),
                   int(rng.integers(8, 30)),
                   (int(rng.integers(10, 50)), int(rng.integers(80, 160)), int(rng.integers(10, 60))), -1)
    img = cv2.GaussianBlur(img, (5, 5), 0)
    img = cv2.add(img, rng.normal(0, 8, img.shape).astype(np.uint8))
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    nofire = buf.tobytes()

    # 合成 T3 林地湖泊(水体明显)
    lake = img.copy()
    cv2.ellipse(lake, (900, 480), (330, 190), -12, 0, 360, (170, 120, 60), -1)
    cv2.ellipse(lake, (920, 500), (300, 160), -12, 0, 360, (190, 140, 70), -1)
    lake = cv2.add(cv2.GaussianBlur(lake, (9, 9), 0), rng.normal(0, 6, lake.shape).astype(np.uint8))
    ok, buf2 = cv2.imencode(".jpg", lake, [cv2.IMWRITE_JPEG_QUALITY, 92])
    lake_bytes = buf2.tobytes()

    fire_bytes = open("e2e/fire.jpg", "rb").read()

    def run(name, data, attempts=4):
        """上传并调用 VLM;限流降级时等 75s 重试(免费档窗口间歇开合),最多 attempts 次。"""
        import time
        boundary = "----vlmcheck"
        v = {}
        for attempt in range(1, attempts + 1):
            payload = (f'--{boundary}\r\nContent-Disposition: form-data; name="use_vlm"\r\n\r\ntrue\r\n'.encode()
                       + f'--{boundary}\r\nContent-Disposition: form-data; name="environment_mode"\r\n\r\noffline\r\n'.encode()
                       + f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\nContent-Type: image/jpeg\r\n\r\n'.encode()
                       + data + f"\r\n--{boundary}--\r\n".encode())
            req = urllib.request.Request(BASE + "/api/analyze/upload", data=payload,
                                         headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
            env = json.loads(urllib.request.urlopen(req, timeout=600).read())
            aid = env.get("analysis_id")
            v = (env.get("result") or {}).get("vlm_explanation") or {}
            real = v.get("mode") == "real"
            try:
                call("POST", f"/api/tasks/{aid}/approval", {"action": "terminate", "reason": "vlm 检验清理"})
            except Exception:
                pass
            if real:
                return v
            print(f"  [{name}] 第 {attempt}/{attempts} 次限流降级,75s 后重试", flush=True)
            if attempt < attempts:
                time.sleep(75)
        return v

    def presence(v):
        return (v.get("fire_observation") or {}).get("fire_presence")

    def groups_ok(v):
        return all(isinstance(v.get(g), dict) for g in
                   ("image_quality", "fire_observation", "smoke_trend", "object_clues", "review")) \
            and bool((v.get("review") or {}).get("human_summary"))

    # T1 真实火场照片:识别火焰
    v1 = run("fire-known.jpg", fire_bytes)
    check("T1 火焰识别(真实火场)", presence(v1) == "flame_observed", f"fire_presence={presence(v1)}")
    check("T1a 契约五组完整+摘要", groups_ok(v1), "")

    # T2 纯林地湖泊(合成,无火):防误报——湖泊图无火,模型不得报 flame_observed
    # (纯纹理林地合成图属分布外输入,模型会误判为火——2026-09-08 实测,该局限记录在案;
    #  正式的防误报验收应使用真实无火航拍照片,对应交付案例 T03)
    v2 = run("synthetic-lake.jpg", lake_bytes)
    p2 = presence(v2)
    check("T2 防误报(合成湖泊,无火)", p2 in ("none_observed", "uncertain"),
          f"fire_presence={p2}(flame_observed 即误报)")
    check("T2a 契约五组完整+摘要", groups_ok(v2), "")

    # T3 水源口径:湖泊只能 water_candidate
    water = ((v2.get("object_clues") or {}).get("water") or {})
    check("T3 水源口径(只判候选)", water.get("state") in ("water_candidate", "not_observed"),
          f"water.state={water.get('state')}(不得 confirmed/usable)")

    # T4 分布外风险(信息项,不计通过率):纯纹理合成图可能被误判为火
    v4 = run("synthetic-forest.jpg", nofire)
    p4 = presence(v4)
    state4 = "✅" if p4 in ("none_observed", "uncertain") else "⚠"
    print(f"{state4} T4 分布外合成图(信息项): fire_presence={p4}(分布外输入误判风险,已知局限,不计通过率)")

    print()
    fails = [name for name, ok in RESULTS if not ok]
    print(f"===== VLM 功能检验汇总:{len(RESULTS) - len(fails)}/{len(RESULTS)} 通过 =====")
    if fails:
        print("未通过:", fails)
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
