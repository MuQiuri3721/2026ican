"""第 9 轮：硬时限约束——时限 30 分钟使全部可控方案超时，输出 time_limit 缺口并判不可控。"""
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
        ok &= report(9, "初始可控方案", True)

        # 时限 1 分钟：任何场景下全部可控候选必然超时（处置窗口下限 > 1 分钟）→
        # 规则 §8.2 选最快方案、输出 time_limit 缺口并判不可控（不依赖实时风速标定）
        session.page.locator(".people-risk input.minute-input").fill("1")
        session.page.get_by_role("button", name="按约束调整").click()
        session.page.wait_for_function(
            "document.querySelector('.plan-summary b')?.textContent?.includes('v2')", timeout=30000
        )
        summary = session.page.locator(".plan-summary").inner_text()
        ok &= report(9, "时限缺口 time_limit", "time_limit" in summary, summary[:160].replace("\n", " "))

        # 判为不可控：hero 结论为增援
        session.page.wait_for_function(
            "document.querySelector('.hero-footer strong')?.textContent?.includes('暂不可控')",
            timeout=20000,
        )
        ok &= report(9, "超时→暂不可控", True)

        # 无时间窗：不产出虚假时间区间
        window_text = summary.split("时间区间：")[1].split("分钟")[0] if "时间区间" in summary else ""
        ok &= report(9, "超时→无时间窗", "—" in window_text, f"window={window_text!r}")

        session.assert_clean_console("round9")
        ok &= report(9, "控制台无错误", True)
        session.screenshot("round9_time_limit")
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
        session.screenshot("round9_failure")
    finally:
        session.cleanup_task()
        session.close(ok)
    if not ok:
        print("detail:", detail)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
