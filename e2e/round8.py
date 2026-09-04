"""第 8 轮：禁用设备约束——禁用 E1/E2 后调整，主方案任务分工不包含被禁用机。"""
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

        # 禁用 E1、E2，出动上限 2 → 调整
        session.page.locator(".people-risk select").nth(1).select_option("2")
        session.page.locator(".uav-disable input[value='E1']").check()
        session.page.locator(".uav-disable input[value='E2']").check()
        session.page.get_by_role("button", name="按约束调整").click()
        session.page.wait_for_function(
            "document.querySelector('.plan-summary b')?.textContent?.includes('v2')", timeout=30000
        )
        ok &= report(8, "调整生成 v2", True)

        # 主方案任务分工 chips 不含 E1/E2
        session.page.wait_for_function(
            "Array.from(document.querySelectorAll('.task-chips b')).filter(b=>['E1','E2'].includes(b.textContent.trim())).length === 0",
            timeout=20000,
        )
        chips = [c.inner_text() for c in session.page.locator(".task-chips b").all()]
        ok &= report(8, "禁用设备未入选", True, f"chips={chips}")

        session.assert_clean_console("round8")
        ok &= report(8, "控制台无错误", True)
        session.screenshot("round8_disabled")
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
        session.screenshot("round8_failure")
    finally:
        session.cleanup_task()
        session.close(ok)
    if not ok:
        print("detail:", detail)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
