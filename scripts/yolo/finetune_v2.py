"""v2 微调：从 v1 best.pt 在 Kaggle 完整 train 集（14,122 张）上继续训练。"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
from ultralytics import YOLO

K = Path(r"C:\Users\15722\.cache\kagglehub\datasets\sayedgamal99\smoke-fire-detection-yolo\versions\1\data")
yaml_path = K / "dfire_v2.yaml"
BASE = Path(r"E:\开发\2026ican\yolo_server\best.pt")

model = YOLO(str(BASE))
results = model.train(
    data=str(yaml_path), epochs=15, imgsz=640, device=0,
    project="runs/dfire", name="yolo11n_v2_ft", patience=5,
    workers=0,  # Windows DataLoader 多进程崩溃规避
)
best = Path(results.save_dir) / "weights" / "best.pt"
out = Path(r"E:\开发\2026ican\yolo_server\best_v2.pt")
out.write_bytes(best.read_bytes())
print("v2 best ->", out)
print("指标:", {k: round(v, 4) for k, v in (results.results_dict or {}).items()})
