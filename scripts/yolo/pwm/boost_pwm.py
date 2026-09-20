# PWM-Net 全学习率 boost 续训：首评（29+10ep，其中 10ep 低 lr 收尾）mAP50 0.563 未发力，
# 论文口径为 300ep 全量。此处从 last.pt 以完整 lr0=0.01 cosine 再训 24 轮（同基准公平补足），
# 分段抗 OOM（每段 4 轮 + 自动重试），与 v1 的对比以终评脚本输出为准。
import os

os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pwm_modules import M2S, PATBlock, WTConvYolo  # noqa: E402

import ultralytics.nn.tasks as tasks  # noqa: E402

for cls in (PATBlock, WTConvYolo, M2S):
    setattr(tasks, cls.__name__, cls)

from ultralytics import YOLO  # noqa: E402

LAST = Path("runs/detect/runs/dfire/pwm11n_v1_resume/weights/last.pt")
SEGMENTS, EPOCHS_PER_SEG = 10, 4  # 24 轮目标；OOM 段自动重来（exist_ok 覆盖写，权重 always 最新 last.pt）

for seg in range(1, SEGMENTS + 1):
    try:
        print(f"\n===== boost 段 {seg}/{SEGMENTS} =====", flush=True)
        m = YOLO(str(LAST))
        m.train(
            data="data/dfire_yolo/dfire.yaml", epochs=EPOCHS_PER_SEG, imgsz=640,
            batch=8, device=0, project="runs/dfire", name="pwm11n_v1_boost",
            exist_ok=True, workers=0, optimizer="SGD", lr0=0.01, lrf=0.05,
            momentum=0.937, patience=EPOCHS_PER_SEG + 1, plots=True,
        )
        print(f"段 {seg} 完成", flush=True)
        time.sleep(5)
    except Exception as e:  # noqa: BLE001
        print(f"段 {seg} 失败：{type(e).__name__} {str(e)[:120]}，15s 后重试", flush=True)
        time.sleep(15)

print("boost 结束：以 pwm11n_v1_boost/weights/best.pt 参与终评", flush=True)
