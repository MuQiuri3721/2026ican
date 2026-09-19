"""aliyun 镜像快速下载 torch/torchvision cu128 轮子（断点续传循环）→ 完成后本地安装。"""
import subprocess, sys, time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
WHEELS = Path(r"E:\开发\2026ican\data\wheels")
BASE = "https://mirrors.aliyun.com/pytorch-wheels/cu128/"
FILES = [
    "torch-2.9.1+cu128-cp311-cp311-win_amd64.whl",
    "torchvision-0.24.1+cu128-cp311-cp311-win_amd64.whl",
]

def remote_size(url):
    for _ in range(8):
        out = subprocess.run(["curl", "-sIL", url], capture_output=True, text=True).stdout
        sizes = [int(l.split()[-1]) for l in out.splitlines() if l.lower().startswith("content-length")]
        if sizes:
            return sizes[-1]
        time.sleep(5)
    return 0

while True:
    pending = []
    for name in FILES:
        f = WHEELS / name
        url = BASE + name.replace("+", "%2B")
        size = remote_size(url)
        current = f.stat().st_size if f.exists() else 0
        if size and current < size:
            pending.append((name, url, current, size))
    if not pending:
        break
    name, url, current, size = pending[0]
    print(f"[{time.strftime('%H:%M:%S')}] {name} {current/1048576:.0f}/{size/1048576:.0f} MB (aliyun)", flush=True)
    subprocess.run(["curl", "-sL", "-C", "-", url, "-o", str(WHEELS / name)])
    time.sleep(3)

print("wheel 全部就绪，本地安装…", flush=True)
subprocess.run([sys.executable, "-m", "pip", "install", "--no-cache-dir", *[str(WHEELS / n) for n in FILES]], check=True)
import torch
print(f"torch {torch.__version__} | cuda: {torch.cuda.is_available()}", flush=True)
