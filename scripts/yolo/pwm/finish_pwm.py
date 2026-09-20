# PWM-Net 断点分段续训 runner：WDDM 环境下其他 GPU 应用（抖音/浏览器/VMware）会中途
# 抢占显存导致 OOM。对策三合一：
# 1) expandable_segments 弹性显存分配，降低碎片与外部抢占敏感度；
# 2) 每段只训 2 轮，段间重建 CUDA 上下文自然释放缓存；
# 3) OOM 自动重试（最多 8 段），从 last.pt 无损续接。
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
SEGMENTS, EPOCHS_PER_SEG = 8, 2  # 最多 8 段 × 2 轮；还差 5 轮，一段崩就再来

for seg in range(1, SEGMENTS + 1):
    try:
        print(f"\n===== 续训段 {seg}/{SEGMENTS} =====", flush=True)
        m = YOLO(str(LAST))
        m.train(
            data="data/dfire_yolo/dfire.yaml", epochs=EPOCHS_PER_SEG, imgsz=640,
            batch=8, device=0, project="runs/dfire", name="pwm11n_v1_resume",
            exist_ok=True, workers=0, optimizer="SGD", lr0=0.001, lrf=0.01,
            momentum=0.937, patience=EPOCHS_PER_SEG + 1, plots=True,
        )
        print(f"段 {seg} 完成", flush=True)
        time.sleep(5)
    except Exception as e:  # noqa: BLE001
        print(f"段 {seg} 失败（大概 OOM）：{type(e).__name__} {str(e)[:120]}，15s 后重试", flush=True)
        time.sleep(15)

print("分段续训结束：以 pwm11n_v1_resume/weights/best.pt 为最终产物", flush=True)
