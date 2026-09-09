# -*- coding: utf-8 -*-
"""实测：指定坐标(模拟发现火情) + 真实照片 VLM 识别 + 下一步闭环。"""
import json
import sys
import time
import urllib.request
import uuid
from pathlib import Path

BASE = "http://127.0.0.1:8000"


def multipart(fields, files):
    boundary = uuid.uuid4().hex
    chunks = []
    for name, value in fields:
        chunks.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode()
        )
    for name, filename, data, ctype in files:
        chunks.append(
            (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; "
                f"filename=\"{filename}\"\r\nContent-Type: {ctype}\r\n\r\n"
            ).encode() + data + b"\r\n"
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def post(path, payload, headers, timeout=300):
    req = urllib.request.Request(BASE + path, data=payload, headers=headers)
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def main():
    image = Path("e2e/_real_images/fire3.jpg").read_bytes()
    body, ctype = multipart(
        [
            ("scene_id", "forest-demo-01"),
            ("use_vlm", "true"),
            ("latitude", "32.10"),
            ("longitude", "118.90"),
            ("environment_mode", "real"),
            ("people_status", "unknown"),
        ],
        [("file", "fire3.jpg", image, "image/jpeg")],
    )
    t0 = time.time()
    env = post("/api/analyze/upload", body, {"Content-Type": ctype})
    print(f"耗时 {time.time() - t0:.0f}s  analysis_id: {env['analysis_id']}")
    res = env["result"]
    scene = res["scene"]
    print("火点GPS:", scene["fire_origin_gps"], " 来源:", scene.get("fire_origin_source"))
    print("相对原点:", scene["fire_origin"])
    fa = res["fire_assessment"]
    print(
        "火情: 面积", fa.get("fire_area_m2"), "m² 增长率", fa.get("growth_rate"),
        "参数来源:", fa.get("fire_params_source"),
    )
    exp = res.get("explanation") or {}
    if isinstance(exp, dict):
        print("VLM mode:", exp.get("mode"), " source:", exp.get("source"))
        obs = exp.get("fire_observation") or {}
        print("VLM visual_scale:", obs.get("visual_scale"), " smoke:", obs.get("smoke_density"))
        review = exp.get("review") or {}
        print("人员判断:", review.get("people_threat", "n/a"))
    plan = res.get("dispatch_plan") or {}
    print("调度: 出动", len(plan.get("selected_uavs", [])), "架  FLP:", fa.get("fire_load_flp"))
    Path("e2e/_coord_vlm_result.json").write_text(
        json.dumps(env, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print("envelope 已存 e2e/_coord_vlm_result.json")
    return env


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
