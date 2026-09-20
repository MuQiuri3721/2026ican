# PWM-Net D-Fire 训练（与 yolo11n_v1 完全同基准：同 5,134 截断子集、同 40 epochs、
# 同 imgsz 640 / 自动 batch / COCO 预训练起点），供 eval_compare.py 同 test 集公平对比。
# 结构注册必须在 YOLO(yaml) 之前完成。
# 用法：python scripts/yolo/pwm/train_pwm.py [--epochs 40] [--data data/dfire_yolo/dfire.yaml]
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pwm_modules import M2S, PATBlock, WTConvYolo  # noqa: E402

import ultralytics.nn.tasks as tasks  # noqa: E402

for cls in (PATBlock, WTConvYolo, M2S):
    setattr(tasks, cls.__name__, cls)

from ultralytics import YOLO  # noqa: E402


def main() -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Train PWM-Net on D-Fire (v1-matched protocol)")
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--data", default="data/dfire_yolo/dfire.yaml")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=16)  # 论文口径；-1 自动探测会以 batch=1 前向，SRM 的 BN 在 1×1 特征上必崩
    parser.add_argument("--workers", type=int, default=0 if sys.platform == "win32" else 8)
    parser.add_argument("--pretrained", default="yolo11n.pt")  # COCO 起点，结构不匹配层自动跳过
    args = parser.parse_args()

    model = YOLO(str(here / "pwm11n.yaml"))
    if Path(args.pretrained).exists():
        model.load(args.pretrained)
        print(f"预训练部分迁移: {args.pretrained}")
    model.info()
    model.train(
        data=args.data, epochs=args.epochs, imgsz=args.imgsz,
        batch=args.batch, device=0, project="runs/dfire", name="pwm11n_v1",
        patience=10, plots=True, workers=args.workers,
        # 论文口径：SGD momentum 0.937, lr0 0.01（与 ultralytics 默认一致，显式声明）
        optimizer="SGD", lr0=0.01, momentum=0.937,
    )
    print("训练完成: runs/dfire/pwm11n_v1/weights/best.pt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
