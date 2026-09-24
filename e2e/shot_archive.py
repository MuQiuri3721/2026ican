"""界面目视截图：任务管理 · 任务归档行表（仅截图，不跑业务断言）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import Session  # noqa: E402

session = Session(headless=True)
page = session.page
try:
    session.goto_app()
    page.get_by_role("button", name="任务管理").click()
    page.locator(".archive-list").wait_for(timeout=10000)
    page.wait_for_timeout(1200)  # 详情行渲染稳定
    session.screenshot("final_archive")
    page.get_by_role("button", name="数据分析").click()
    page.wait_for_timeout(600)
    session.screenshot("final_analysis_after_archive")
    errors = session.errors()
    print("page errors:", errors or "none")
finally:
    session.close(passed=True, cleanup=False)
