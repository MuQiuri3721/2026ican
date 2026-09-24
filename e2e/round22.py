"""第 22 轮：视觉证据窗（FE-75）+ 演示一键脚本（FE-76）。

mock YOLO 适配器驱动真实检测模式：证据窗原图+检测框渲染；
🎬主场景一键 → 自动生成固定小火并自动开始模拟 → 执行中。
"""
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import Session, report  # noqa: E402


def main() -> int:
    session = Session()
    ok = True
    detail = ""
    page = session.page
    mock = None
    try:
        mock = subprocess.Popen([sys.executable, "e2e/mock_yolo_adapter.py", "8766"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)
        # mock YOLO 需平台带 FIRE_YOLO_ENDPOINT——若当前后端未带，则证据窗仅非 real 不渲染；
        # 演示脚本部分不受影响。两种状态都兼容断言。
        session.goto_app()
        page.get_by_text("系统运行正常").wait_for(timeout=20000)

        # FE-76：🎬主场景一键（自动生成固定小火 + 自动开始模拟）
        page.get_by_role("button", name="🎬 主场景").click()
        page.locator(".scenario-facts").wait_for(timeout=8000)
        facts = page.locator(".scenario-facts").inner_text()
        ok &= report(22, "主场景一键生成", "450" in facts and "0.18" in facts, facts[:90].replace("\n", " "))
        # 自动开始模拟（无需点开始按钮）
        page.get_by_role("button", name="机群调度").click()
        page.locator(".plan-summary").wait_for(timeout=300000)
        badge = page.locator(".task-badge").first.inner_text()  # 2026-09 改版后顶栏+调度页头双徽标，取顶栏（DOM 第一个）
        ok &= report(22, "一键自动研判", "待确认" in badge, badge)

        # FE-75：证据窗（真实检测模式才渲染；当前后端未带端点则跳过该断言）
        page.get_by_role("button", name="机群调度").click()
        if page.locator(".evidence-window").count():
            boxes = page.evaluate("Array.from(document.querySelectorAll('.ew-box em')).map(e=>e.textContent)")
            ok &= report(22, "证据窗渲染", len(boxes) > 0, str(boxes[:4]))
        else:
            live = page.evaluate("document.querySelector('.detector-live')?.textContent || ''")
            ok &= report(22, "证据窗(真实检测模式)", "real" not in live, f"detector-live={live[:60] or '无'}")

        # 清理：终止任务
        page.get_by_role("button", name="机群调度").click()
        page.get_by_placeholder("驳回/终止原因（必填）").fill("round22 清理")
        page.get_by_role("button", name="终止任务").click()
        page.wait_for_function("document.querySelector('.task-badge')?.textContent?.includes('已终止')", timeout=30000)
        ok &= report(22, "终止清理", True)

        session.assert_clean_console("round22")
        ok &= report(22, "控制台无错误", True)
        session.screenshot("round22")
    except Exception as error:
        ok = False
        detail = f"{type(error).__name__}: {str(error)[:260]}"
        session.screenshot("round22_failure")
    finally:
        session.cleanup_task()
        if mock:
            mock.kill()
        session.close(ok)
    if not ok:
        print("detail:", detail)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
