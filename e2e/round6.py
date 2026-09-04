"""第 6 轮：重启恢复（UI）——历史任务列表来自 SQLite，点击恢复历史任务。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import Session, report  # noqa: E402


def main() -> int:
    session = Session()
    ok = True
    detail = ""
    try:
        session.goto_app()
        session.page.get_by_text("系统运行正常").wait_for(timeout=15000)

        # 历史任务页（数据来自后端 /api/analyzes，重启后应有记录）；FE-12 后工具栏页签为 role=tab
        session.page.get_by_role("tab", name="历史任务").click()
        session.page.locator(".history-row").first.wait_for(timeout=15000)
        rows = session.page.locator(".history-row").count()
        ok &= report(6, "历史任务条目", rows >= 3, f"rows={rows}")

        # 点击第一条恢复：界面载入该任务的方案与状态
        session.page.locator(".history-row").first.click()
        session.page.wait_for_function(
            "document.querySelector('.plan-summary')?.textContent?.includes('FLP')",
            timeout=20000,
        )
        ok &= report(6, "历史任务恢复", True)

        # 日志页应展示恢复任务的事件（来自 events 接口）
        session.page.get_by_role("button", name="任务日志").click()
        session.page.locator(".full-logs > div").first.wait_for(timeout=15000)
        ok &= report(6, "恢复任务事件", True)

        session.assert_clean_console("round6")
        ok &= report(6, "控制台无错误", True)
        session.screenshot("round6_recovery")
    except Exception as error:
        ok = False
        detail = str(error)[:200]
        try:
            detail += " | badge=" + session.page.locator(".task-badge").inner_text()
        except Exception:
            pass
        session.screenshot("round6_failure")
    finally:
        session.cleanup_task()
        session.close(ok)
    if not ok:
        print("detail:", detail)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
