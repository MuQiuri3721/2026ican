# -*- coding: utf-8 -*-
"""PDF 素材截图：七页导航 + 恢复任务 A 的调度页富状态。从项目根运行。"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import Session  # noqa: E402

OUT = Path("docs/pdf-assets/screenshots")
OUT.mkdir(parents=True, exist_ok=True)
TASK_A = "analysis-f59c7dc7ab53"

s = Session()
s.goto_app()
s.page.wait_for_timeout(1500)

def shot(name):
    s.page.wait_for_timeout(600)
    s.page.screenshot(path=str(OUT / f"{name}.png"))
    print("shot", name)

# 1 态势总览
s.page.get_by_role("button", name="态势总览").click()
s.page.wait_for_timeout(2500)
shot("1-overview-map")

# 2 火情监测（任务输入区）
s.page.get_by_role("button", name="火情监测").click()
shot("2-analysis-upload")

# 3 资源管理
s.page.get_by_role("button", name="资源管理").click()
shot("3-fleet")

# 4 Agent 协作
s.page.get_by_role("button", name="Agent 协作").click()
shot("4-agents")

# 5 任务管理
s.page.get_by_role("button", name="任务管理").click()
s.page.wait_for_timeout(1200)
shot("5-history")

# 6 恢复任务 A → 机群调度（决策区 + 反馈报告区）
try:
    s.page.locator(f".history-row", has_text=TASK_A).first.click()
    s.page.wait_for_timeout(2000)
    print("restored", TASK_A)
except Exception as e:
    print("restore failed:", str(e)[:120])
s.page.get_by_role("button", name="机群调度").click()
s.page.wait_for_timeout(1800)
shot("6-dispatch-plan")
s.page.locator(".decision-panel").evaluate("el => el.scrollTop = el.scrollHeight")
s.page.wait_for_timeout(800)
shot("7-dispatch-feedback")

# 7 系统设置
s.page.get_by_role("button", name="系统设置").click()
shot("8-settings")

s.close(True)
print("done")
