"""第 4 轮：调整约束表单——出动上限/禁用设备生成新方案版本，驳回释放资源。"""
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
        session.page.set_input_files("input[type=file]", "e2e/small-fire.jpg")
        session.page.get_by_text("影像已接入").wait_for(timeout=10000)
        session.page.get_by_role("button", name="启动智能研判").click()
        session.page.wait_for_function(
            "document.querySelector('.plan-summary')?.textContent?.includes('FLP：')", timeout=150000
        )
        ok &= report(4, "方案就绪", True)

        # 约束：出动上限 2、禁用 E4；点击按约束调整
        session.page.locator(".people-risk select").nth(1).select_option("2")
        session.page.locator(".uav-disable input[value='E4']").check()
        session.page.get_by_role("button", name="按约束调整").click()
        # 调整后审批按钮组仍在（analysisId 未丢失）
        session.page.get_by_role("button", name="批准主方案").wait_for(timeout=30000)
        ok &= report(4, "调整后仍可审批", True)
        session.page.wait_for_function(
            "document.querySelector('.plan-summary b')?.textContent?.includes('v2')", timeout=30000
        )
        ok &= report(4, "新方案版本 v2", True)
        summary = session.page.locator(".plan-summary").inner_text()
        ok &= report(4, "重规划原因含 manual_adjust", "manual_adjust" in summary, summary[-120:].replace("\n", " "))

        # 驳回（填原因）→ 仍在待确认、资源释放
        session.page.get_by_placeholder("驳回/终止原因（必填）").fill("E2E 驳回验证")
        session.page.get_by_role("button", name="驳回").click()
        session.page.wait_for_function(
            "document.querySelector('.task-badge')?.textContent?.includes('待确认')", timeout=30000
        )
        ok &= report(4, "驳回→待确认", True)

        session.assert_clean_console("round4")
        ok &= report(4, "控制台无错误", True)
        session.screenshot("round4_adjust")
    except Exception as error:
        ok = False
        detail = str(error)[:200]
        try:
            detail += " | badge=" + session.page.locator(".task-badge").inner_text()
            notice = session.page.locator(".notice")
            if notice.count():
                detail += " | notice=" + notice.inner_text()[:120]
        except Exception:
            pass
        session.screenshot("round4_failure")
    finally:
        session.cleanup_task()
        session.close(ok)
    if not ok:
        print("detail:", detail)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
