# -*- coding: utf-8 -*-
"""证据截图：每节 1-2 张界面证据（3.3 环境/总览、3.4 方案审批、3.5 机群卡片、3.6 趋势回放）。
从项目根运行：python docs/pdf-assets/capture_evidence.py
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
EV = ROOT / "docs" / "pdf-assets" / "evidence"
EV.mkdir(exist_ok=True)

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1680, "height": 1000}, device_scale_factor=2)
    pg.goto("http://localhost:5173/")
    pg.wait_for_timeout(8000)

    # ---- 3.3 证据1：火情监测页现场环境卡（右栏，含来源/坡度/最近水源） ----
    pg.get_by_role("button", name="火情监测", exact=True).click()
    pg.wait_for_timeout(2500)
    env_card = pg.locator("section", has_text="现场环境").last
    try:
        env_card.screenshot(path=str(EV / "e33-environment-panel.png"))
        print("ok e33-environment-panel")
    except Exception as e:
        print("env card fail:", str(e)[:80])

    # ---- 3.4 证据：生成随机火情 → 模拟 → 方案审批卡 ----
    pg.evaluate("document.querySelector('.fm-tools-drawer') && (document.querySelector('.fm-tools-drawer').open = true)")
    pg.get_by_role("button", name="生成随机火情").click()
    pg.wait_for_timeout(1500)
    pg.get_by_role("button", name="开始模拟").click()
    pg.wait_for_function("""() => Array.from(document.querySelectorAll('button')).some(b => b.textContent.includes('批准主方案'))""", timeout=240000)
    pg.get_by_role("button", name="机群调度").click()
    pg.wait_for_timeout(2500)
    pg.screenshot(path=str(EV / "e34-dispatch-approval.png"))
    print("ok e34-dispatch-approval")
    plan = pg.locator(".plan-summary").first
    try:
        plan.screenshot(path=str(EV / "e34-plan-summary.png"))
        print("ok e34-plan-summary")
    except Exception as e:
        print("plan summary fail:", str(e)[:80])

    # ---- 3.5 证据：批准后资源管理页无人机卡片网格（执行态 SOC/药剂） ----
    pg.evaluate("""(() => {
      const reason = document.querySelector('input[placeholder*="驳回"], input[placeholder*="终止"]');
      const approve = Array.from(document.querySelectorAll('button')).find(b => b.textContent.includes('批准主方案'));
      approve && approve.click();
    })()""")
    pg.wait_for_timeout(4000)
    pg.get_by_role("button", name="资源管理").click()
    pg.wait_for_timeout(2500)
    pg.screenshot(path=str(EV / "e35-fleet-cards.png"))
    print("ok e35-fleet-cards")

    # ---- 3.6 证据：数据分析页（趋势曲线 + 回放 + 报告） ----
    pg.get_by_role("button", name="数据分析").click()
    pg.wait_for_timeout(3000)
    pg.screenshot(path=str(EV / "e36-analysis-replay.png"))
    print("ok e36-analysis-replay")

    # ---- 3.3 证据2：态势总览整页（地图水源等高线规划区） ----
    pg.get_by_role("button", name="态势总览").click()
    pg.wait_for_timeout(6000)
    pg.screenshot(path=str(EV / "e33-overview.png"))
    print("ok e33-overview")
    b.close()
print("EVIDENCE DONE")
