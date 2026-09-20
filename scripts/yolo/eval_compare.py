"""v1/v2 同基准公平对比：两个模型在 Kaggle val（3,099 张）上评测。"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
from ultralytics import YOLO

yaml = r"C:\Users\15722\.cache\kagglehub\datasets\sayedgamal99\smoke-fire-detection-yolo\versions\1\data\dfire_v2.yaml"
for name, weights in [("v1(5k子集40ep)", r"E:\开发\2026ican\yolo_server\best.pt"),
                      ("v2(全量微调)", r"E:\开发\2026ican\yolo_server\best_v2.pt")]:
    m = YOLO(weights)
    r = m.val(data=yaml, imgsz=640, device=0, verbose=False, workers=0)
    d = r.results_dict
    print(f"{name}: P={d['metrics/precision(B)']:.3f} R={d['metrics/recall(B)']:.3f} "
          f"mAP50={d['metrics/mAP50(B)']:.3f} mAP50-95={d['metrics/mAP50-95(B)']:.3f}", flush=True)
