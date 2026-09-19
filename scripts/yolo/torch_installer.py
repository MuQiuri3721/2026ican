"""轮子装填器：等 torch/torchvision wheel 下载完成 → 本地 pip 安装 → 验证 CUDA。"""
import subprocess, sys, time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
WHEELS = Path(r"E:\开发\2026ican\data\wheels")
TARGETS = {
    "torch-2.9.1+cu128-cp311-cp311-win_amd64.whl": None,
    "torchvision-0.24.1+cu128-cp311-cp311-win_amd64.whl": None,
}
for name in TARGETS:
    out = subprocess.run(["curl", "-sIL", f"https://download.pytorch.org/whl/cu128/{name.replace('+', '%2B')}"],
                         capture_output=True, text=True).stdout
    sizes = [int(l.split()[-1]) for l in out.splitlines() if l.lower().startswith("content-length")]
    TARGETS[name] = sizes[-1] if sizes else 0

while True:
    ready = all((WHEELS / n).exists() and (WHEELS / n).stat().st_size >= s > 0 for n, s in TARGETS.items())
    if ready:
        print("轮子全部就绪，本地安装…", flush=True)
        subprocess.run([sys.executable, "-m", "pip", "install", "--no-cache-dir",
                        *[str(WHEELS / n) for n in TARGETS]], check=True)
        break
    time.sleep(60)
print("安装完成，验证 CUDA…", flush=True)
import torch
print("torch", torch.__version__, "| cuda:", torch.cuda.is_available(), flush=True)
