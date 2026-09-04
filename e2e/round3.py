"""第 3 轮：审批闭环——批准→执行→资源锁→反馈轮次→终止。"""
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

        # 小火场景（可控）
        session.page.set_input_files("input[type=file]", str(Path(__file__).resolve().parent / "small-fire.jpg"))
        session.page.get_by_text("影像已接入").wait_for(timeout=10000)
        session.page.get_by_role("button", name="启动智能研判").click()
        session.page.wait_for_function(
            "document.querySelector('.plan-summary')?.textContent?.includes('FLP：')", timeout=150000
        )
        ok &= report(3, "小火方案就绪", True)

        # 批准主方案 → 执行中
        session.page.get_by_role("button", name="批准主方案").click()
        session.page.wait_for_function(
            "document.querySelector('.task-badge')?.textContent?.includes('执行中')", timeout=30000
        )
        ok &= report(3, "批准→执行中", True)

        # 反馈轮次：执行下一轮监测 → Round 1 before/after
        session.page.get_by_role("button", name="执行下一轮监测").click()
        session.page.locator(".round-list > div").first.wait_for(timeout=60000)
        round_text = session.page.locator(".round-list > div").first.inner_text()
        ok &= report(3, "反馈轮次 Round 1", "Round 1" in round_text and "before FLP" in round_text, round_text[:100].replace("\n", " "))

        # 任务日志应有审批与监测事件（SSE/轮询已拉取）
        logs = session.page.locator(".logs").inner_text()
        ok &= report(3, "审批事件入日志", "方案审批" in logs or "approval" in logs, logs[:80].replace("\n", " "))

        # 终止任务：原因必填（先验证空原因被拦截，再填原因终止）
        session.page.get_by_role("button", name="终止任务").click()
        session.page.get_by_text("驳回或终止必须在原因框中说明原因。").wait_for(timeout=5000)
        ok &= report(3, "空原因拦截", True)
        session.page.get_by_placeholder("驳回/终止原因（必填）").fill("处置完成，E2E 终止")
        session.page.get_by_role("button", name="终止任务").click()
        session.page.wait_for_function(
            "document.querySelector('.task-badge')?.textContent?.includes('已终止')", timeout=30000
        )
        ok &= report(3, "终止→已终止", True)

        session.assert_clean_console("round3")
        ok &= report(3, "控制台无错误", True)
        session.screenshot("round3_closedloop")
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
        session.screenshot("round3_failure")
    finally:
        session.cleanup_task()
        session.close(ok)
    if not ok:
        print("detail:", detail)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
