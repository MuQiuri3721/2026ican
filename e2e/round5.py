"""第 5 轮：SSE 事件流连接与任务报告在线查看。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import Session, report  # noqa: E402


def main() -> int:
    session = Session()
    ok = True
    detail = ""
    streams = []
    try:
        def on_response(resp):
            if "events/stream" in resp.url:
                streams.append((resp.status, resp.headers.get("content-type", "")))
        session.page.on("response", on_response)

        session.goto_app()
        session.page.get_by_text("系统运行正常").wait_for(timeout=15000)
        session.page.set_input_files("input[type=file]", "e2e/small-fire.jpg")
        session.page.get_by_text("影像已接入").wait_for(timeout=10000)
        session.page.get_by_role("button", name="启动智能研判").click()
        session.page.wait_for_function(
            "document.querySelector('.plan-summary')?.textContent?.includes('FLP：')", timeout=150000
        )

        # SSE：研判完成后自动建立事件流连接（content-type=text/event-stream）
        session.page.wait_for_function(
            "fetch('/api/analyze/' + (document.querySelector('.plan-summary b') ? '' : '')).then(()=>0)",
            timeout=1000,
        ) if False else None
        deadline = 0
        while not streams and deadline < 30:
            session.page.wait_for_timeout(500)
            deadline += 1
        sse_ok = bool(streams) and streams[0][0] == 200 and "text/event-stream" in streams[0][1]
        ok &= report(5, "SSE 事件流连接", sse_ok, str(streams[:2]))

        # 批准产生新事件 → 日志更新（SSE 推送 + 事件拉取双路径）
        before = session.page.locator(".logs").inner_text()
        session.page.get_by_role("button", name="批准主方案").click()
        session.page.wait_for_function(
            "document.querySelector('.task-badge')?.textContent?.includes('执行中')", timeout=30000
        )
        session.page.wait_for_function(
            "document.querySelector('.logs')?.textContent?.includes('方案审批：approve')", timeout=15000
        )
        after = session.page.locator(".logs").inner_text()
        ok &= report(5, "审批事件实时上屏", "方案审批：approve" in after and after != before, "")

        # 报告在线查看：打开 → JSON 含 task_id 与 plan_versions → 收起
        session.page.get_by_role("button", name="在线查看报告").click()
        session.page.locator(".report-viewer pre").wait_for(timeout=30000)
        session.page.wait_for_function(
            "document.querySelector('.report-viewer pre')?.textContent?.includes('plan_versions')",
            timeout=30000,
        )
        report_text = session.page.locator(".report-viewer pre").text_content() or ""
        ok &= report(5, "报告 JSON 完整", '"plan_versions"' in report_text and '"events"' in report_text, f"len={len(report_text)}")
        session.page.get_by_role("button", name="收起报告").click()
        ok &= report(5, "报告收起", session.page.locator(".report-viewer").count() == 0, "")

        session.assert_clean_console("round5")
        ok &= report(5, "控制台无错误", True)
        session.screenshot("round5_sse_report")
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
        session.screenshot("round5_failure")
    finally:
        session.cleanup_task()
        session.close(ok)
    if not ok:
        print("detail:", detail)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
