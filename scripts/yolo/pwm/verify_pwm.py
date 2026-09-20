# PWM-Net 结构验证：注册自定义模块 → 构建 → 前向 → 参数量/FLOPs 报告。
# 期望参数量与论文口径同量级（论文 7.8M；复现细节差异允许偏离）。
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pwm_modules import M2S, PATBlock, WTConvYolo  # noqa: E402

import ultralytics.nn.tasks as tasks  # noqa: E402

for cls in (PATBlock, WTConvYolo, M2S):
    setattr(tasks, cls.__name__, cls)


def main() -> int:
    from ultralytics import YOLO

    model = YOLO(str(Path(__file__).resolve().parent / "pwm11n.yaml"))
    n_params = sum(p.numel() for p in model.model.parameters()) / 1e6
    print(f"\nPWM-Net 参数量: {n_params:.2f}M (论文口径 7.8M)")

    model.model.eval()
    with torch.no_grad():
        out = model.model(torch.zeros(1, 3, 640, 640))
    kind = type(out[-1] if isinstance(out, (list, tuple)) else out).__name__
    print(f"640x640 前向 OK，输出头数: {len(out) if isinstance(out, (list, tuple)) else 1} ({kind})")

    # 训练模式前向（loss 路径）：伪造一批 640 图与标签
    model.model.train()
    fake_batch = {
        "img": torch.rand(2, 3, 640, 640),
        "batch_idx": torch.tensor([0.0, 0.0, 1.0]),
        "cls": torch.tensor([[0.0], [1.0], [1.0]]),
        "bboxes": torch.tensor([[0.5, 0.5, 0.2, 0.3], [0.3, 0.4, 0.1, 0.1], [0.7, 0.6, 0.2, 0.2]]),
    }
    model.model.args = {**getattr(model.model, "args", {}), "box": 7.5, "cls": 0.5, "dfl": 1.5}
    from ultralytics.utils import IterableSimpleNamespace

    model.model.args = IterableSimpleNamespace(**model.model.args)
    model.model.criterion = None
    result = model.model.loss(fake_batch)
    loss = result[0] if isinstance(result, tuple) else result
    parts = [round(float(v), 3) for v in loss.flatten().tolist()[:3]]
    print(f"训练 loss 路径 OK: total={sum(parts):.4f}, parts(box/cls/dfl)={parts}")

    fps_img = torch.rand(1, 3, 640, 640)
    model.model.eval()
    with torch.no_grad():
        for _ in range(3):
            model.model(fps_img)
        import time

        t0 = time.time()
        for _ in range(20):
            model.model(fps_img)
        dt = (time.time() - t0) / 20 * 1000
    print(f"推理延迟(CPU 参考): {dt:.0f}ms/帧")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
