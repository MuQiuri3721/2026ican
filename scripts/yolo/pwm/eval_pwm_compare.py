# 三模型同基准终评：v1 / v2 / PWM-Net 在官方 D-Fire test（4,306 张）上同协议评测。
# 协议：imgsz 640 / batch 8（防 OOM）/ device 0，与 eval_compare.py、eval_dfire.py 口径一致。
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pwm_modules import M2S, PATBlock, WTConvYolo  # noqa: E402

import ultralytics.nn.tasks as tasks  # noqa: E402

for cls in (PATBlock, WTConvYolo, M2S):
    setattr(tasks, cls.__name__, cls)  # v1/v2 加载不需要，注册无害

from ultralytics import YOLO  # noqa: E402

yaml = "data/dfire_yolo/dfire_test.yaml"
models = [
    ("v1 (5k子集40ep, 生产)", "yolo_server/best.pt"),
    ("v2 (全量微调)", "yolo_server/best_v2.pt"),
    ("PWM-Net (复现, 29+10ep)", "runs/detect/runs/dfire/pwm11n_v1_resume/weights/best.pt"),
]
results = []
for name, weights in models:
    m = YOLO(weights)
    r = m.val(data=yaml, imgsz=640, batch=8, device=0, verbose=False, workers=0)
    d = r.results_dict
    p, rc = d["metrics/precision(B)"], d["metrics/recall(B)"]
    m50, m5095 = d["metrics/mAP50(B)"], d["metrics/mAP50-95(B)"]
    n_params = sum(x.numel() for x in m.model.parameters()) / 1e6
    results.append((name, n_params, p, rc, m50, m5095))
    print(f"{name}: params={n_params:.2f}M P={p:.3f} R={rc:.3f} mAP50={m50:.3f} mAP50-95={m5095:.3f}", flush=True)

print("\n===== 终评结论（官方 test 4,306 张同基准）=====", flush=True)
best = max(results, key=lambda x: x[4])
for name, n_params, p, rc, m50, m5095 in results:
    mark = " ← 胜出" if name == best[0] else ""
    print(f"{name}: mAP50={m50:.3f}{mark}", flush=True)
