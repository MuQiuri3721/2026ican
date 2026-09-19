"""反复测试优化轮的套件跑批器：一次跑完 E2E R1-R19，输出紧凑摘要与失败详情。

用法：python e2e/_suite_runner.py [轮次标签]
输出：每轮 pass/fail 计数 + 失败轮次的 detail 尾部（便于当轮修复）。
"""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LABEL = sys.argv[1] if len(sys.argv) > 1 else "loop"
failures = []
start = time.time()

for n in range(1, 22):
    proc = subprocess.run([sys.executable, str(ROOT / "e2e" / f"round{n}.py")],
                          capture_output=True, text=True, cwd=ROOT, timeout=600)
    out = proc.stdout + proc.stderr
    passes = out.count("PASS")
    fails = out.count("FAIL") + out.count("detail:")
    status = "OK " if fails == 0 and proc.returncode == 0 else "FAIL"
    print(f"[{LABEL}] round{n}: pass={passes} fail={fails} {status}", flush=True)
    if fails or proc.returncode != 0:
        tail = "\n".join(out.strip().splitlines()[-6:])
        failures.append((n, tail))

print(f"[{LABEL}] 总耗时 {time.time() - start:.0f}s | 失败轮: {[f[0] for f in failures] or '无'}", flush=True)
for n, tail in failures:
    print(f"--- round{n} 失败详情 ---", flush=True)
    print(tail, flush=True)
sys.exit(1 if failures else 0)
