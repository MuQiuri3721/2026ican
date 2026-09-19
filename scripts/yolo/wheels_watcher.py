"""分离进程下载看护：torch/torchvision wheel + test.tar 断点续传→本地安装→验证 CUDA。"""
import subprocess, sys, time, urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
WHEELS = Path(r"E:\开发\2026ican\data\wheels")
DFIRE = Path(r"E:\开发\2026ican\data\dfire")
LOG = DFIRE / "watchers.log"

def log(m):
    line = f"[{time.strftime('%H:%M:%S')}] {m}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as h:
        h.write(line + "\n")

def remote_size(url):
    for _ in range(5):
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=60) as r:
                return int(r.headers["Content-Length"])
        except Exception:
            time.sleep(10)
    return 0

jobs = [
    ("torch-2.9.1+cu128-cp311-cp311-win_amd64.whl", "https://download.pytorch.org/whl/cu128/"),
    ("torchvision-0.24.1+cu128-cp311-cp311-win_amd64.whl", "https://download.pytorch.org/whl/cu128/"),
    ("test.tar", "https://huggingface.co/datasets/hanvithSai/gavin-dfire-raw/resolve/main/"),
]
plan = []
for name, base in jobs:
    directory = WHEELS if name.endswith(".whl") else DFIRE
    size = remote_size(base + name.replace("+", "%2B"))
    plan.append((name, directory, base, size))
    log(f"{name}: 远端 {size/1048576:.0f} MB")

while True:
    all_done = True
    for name, directory, base, size in plan:
        f = directory / name
        current = f.stat().st_size if f.exists() else 0
        if size and current >= size:
            continue
        all_done = False
        log(f"{name} {current/1048576:.0f}/{size/1048576:.0f} MB 续传")
        subprocess.run(["curl", "-sL", "-C", "-", base + name.replace("+", "%2B"), "-o", str(f)])
        time.sleep(5)
    if all_done:
        break
log("全部下载完成，本地安装 wheel…")
wheels = [str(directory / name) for name, directory, _, _ in plan if name.endswith(".whl")]
subprocess.run([sys.executable, "-m", "pip", "install", "--no-cache-dir", *wheels], check=True)
import torch  # noqa
log(f"torch {torch.__version__} | cuda: {torch.cuda.is_available()}")
