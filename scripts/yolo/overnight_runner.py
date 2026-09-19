"""过夜自动训练 runner：等待 train.tar 与 CUDA torch 就绪 → 解包 → 训练 → 导出 best.pt。

用系统分离进程启动（不依赖 ZCode 会话）：
  powershell -Command "Start-Process -WindowStyle Hidden python -ArgumentList 'E:\开发\2026ican\scripts\yolo\overnight_runner.py'"
日志：data/dfire/train_runner.log（tail -f 可看进度）
"""
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
TAR = ROOT / "data" / "dfire" / "train.tar"
LOG = ROOT / "data" / "dfire" / "train_runner.log"


def log(message: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {message}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def remote_size() -> int:
    for _ in range(5):
        try:
            out = subprocess.run(
                ["curl", "-sIL", "https://huggingface.co/datasets/hanvithSai/gavin-dfire-raw/resolve/main/train.tar"],
                capture_output=True, text=True, timeout=60).stdout
            sizes = [int(line.split()[-1]) for line in out.splitlines() if line.lower().startswith("content-length")]
            if sizes:
                return sizes[-1]
        except Exception:
            pass
        time.sleep(10)
    return 0


def main() -> None:
    log("runner 启动：等待 train.tar 与 CUDA torch 就绪")
    expected = remote_size()
    log(f"远端大小: {expected / 1048576:.0f} MB")

    # 1) 续传 train.tar（curl -C - 循环直到大小一致）
    while True:
        current = TAR.stat().st_size if TAR.exists() else 0
        if expected and current >= expected:
            log(f"train.tar 下载完成（{current / 1048576:.0f} MB）")
            break
        log(f"train.tar {current / 1048576:.0f}/{expected / 1048576:.0f} MB，续传中…")
        subprocess.run(["curl", "-sL", "-C", "-", "--retry", "5",
                        "https://huggingface.co/datasets/hanvithSai/gavin-dfire-raw/resolve/main/train.tar",
                        "-o", str(TAR)])
        time.sleep(5)

    # 2) 等 CUDA torch（每晚一分钟重查一次；torch 安装由 pip 重试脚本负责）
    deadline = time.time() + 3600 * 10
    while time.time() < deadline:
        try:
            import torch
            if torch.cuda.is_available():
                log(f"torch {torch.__version__} CUDA 就绪（{torch.cuda.get_device_name(0)}）")
                break
            log(f"torch {torch.__version__} 无 CUDA，继续等待安装…")
        except ImportError:
            log("torch 未装，继续等待…")
        except Exception as error:
            log(f"torch 导入异常（可能半安装）: {error}")
        time.sleep(60)
    else:
        log("超时未等到 CUDA torch，退出（修复安装后重跑本 runner）")
        return

    # 3) 解包 + 训练 + 导出
    log("解包 train.tar …")
    import tarfile
    with tarfile.open(TAR) as tar:
        tar.extractall(TAR.parent)

    log("开始训练 YOLO11n（40 epochs）…")
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "yolo" / "train_dfire.py"),
                             "--epochs", "40"], cwd=ROOT)
    log(f"训练脚本退出码: {result.returncode}")
    best = ROOT / "yolo_server" / "best.pt"
    log("best.pt 就绪" if best.exists() else "best.pt 未生成，检查训练日志")


if __name__ == "__main__":
    main()
