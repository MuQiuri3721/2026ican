"""演示开播前自检(demo_readiness)。

逐项检查后端/前端/模型在线状态与 Key 配置,全绿即可开录(E-3 演示材料配套,
docs/demo-script.md §〇)。只读变量名与状态,绝不打印任何 Key 值。

用法:python e2e/demo_readiness.py
退出码:0=硬检查全部通过;1=存在必须处理的项。
"""
import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
BACKEND = "http://127.0.0.1:8000"
FRONTEND = "http://localhost:5173"  # vite 默认绑 ::1,127.0.0.1 探不到

RESULTS = []


def check(name, ok, detail="", hard=True, hint=""):
    RESULTS.append((name, bool(ok), detail, hard, hint))
    mark = "✅" if ok else ("❌" if hard else "⚠")
    print(f"{mark} {name}" + (f" | {detail}" if detail else "") + (f" → {hint}" if (hint and not ok) else ""))
    return ok


def main() -> int:
    # 1. .env 与 Key 变量(只看有无)
    env_path = ROOT / ".env"
    env_values = {}
    if check(".env 存在", env_path.exists(), hard=True, hint="复制根目录 .env.example 为 .env 并填 Key"):
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key, _, value = line.partition("=")
                env_values[key.strip()] = value.strip()
    check("GLM 文本模型 Key 已配(FIREOPS_LLM_API_KEY)", bool(env_values.get("FIREOPS_LLM_API_KEY")),
          hard=True, hint="六角色研判/指挥员问答需要;无则全程离线规则模式")
    check("VLM 视觉模型 Key 已配(FIRE_VLM_API_KEY)", bool(env_values.get("FIRE_VLM_API_KEY")),
          hard=True, hint="VLM 解释块需要;无则回落规则解释")

    # 2. 后端
    backend_ok = check("后端 :8000 在线", _get(f"{BACKEND}/api/health") is not None,
                       hard=True, hint="cd backend && python -m uvicorn app.main:app --port 8000")
    if backend_ok:
        # 预热环境缓存：冷启动首次研判会现抓 GIS/气象（30-90s），提前打一次让演示首跑即快
        _get(f"{BACKEND}/api/environment?scene_id=forest-demo-01&latitude=32.0725&longitude=118.8415", timeout=240)
        status = _get(f"{BACKEND}/api/project-status") or {}
        check("VLM 接入状态=configured", status.get("vlm") == "configured",
              f"实际 {status.get('vlm')}", hard=True, hint="重启后端以加载 .env")
        llm = _get(f"{BACKEND}/api/llm-status") or {}
        check("GLM 文本模型在线", bool(llm.get("available")),
              f"mode={llm.get('mode')} model={llm.get('model')} fail_streak={llm.get('fail_streak')}",
              hard=False, hint="免费档可能临时限流;演示可照常,讲解口径见 demo-script §九")

    # 3. 前端
    try:
        frontend_ok = requests.get(FRONTEND, timeout=5).status_code == 200
    except Exception:
        frontend_ok = False
    check("前端 :5173 在线", frontend_ok, hard=True,
          hint="cd frontend && npm run dev")

    # 4. 演示存档提示(非检查项)
    if (ROOT / "data" / "analysis_store.db").exists():
        print("ℹ 存在历史任务存档 data/analysis_store.db;录制前可删除并重启后端以清空历史页")

    failed = [name for name, ok, _, hard, _ in RESULTS if not ok and hard]
    print(f"\n结论:{'可以开录 ✅' if not failed else '存在 ' + str(len(failed)) + ' 项硬阻塞 ❌'}")
    return 0 if not failed else 1


def _get(url, timeout=8):
    try:
        return json.loads(requests.get(url, timeout=timeout).text)
    except Exception:
        return None


if __name__ == "__main__":
    raise SystemExit(main())
