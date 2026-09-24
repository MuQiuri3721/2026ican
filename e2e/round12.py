"""第 12 轮：演训模拟——随机生成紫金山火情、地图预览、开始模拟、批准出动、推演闭环。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import Session, report  # noqa: E402


def main() -> int:
    session = Session()
    ok = True
    detail = ""
    page = session.page
    try:
        session.goto_app()

        # 生成随机火情
        page.get_by_role("button", name="火情监测", exact=True).click()
        page.get_by_role("button", name="生成随机火情").click()
        page.locator(".scenario-facts").wait_for(timeout=8000)
        facts = page.locator(".scenario-facts").inner_text()
        ok &= report(12, "随机火情生成", "°E" in facts and "m²" in facts, facts[:110].replace("\n", " "))

        # 地图预览：演训火点标记 + 火圈
        page.get_by_role("button", name="态势总览").click()
        preview = page.locator(".tmap-fire", has_text="演训火点")
        preview.wait_for(timeout=20000)
        ok &= report(12, "火点地图预览", "演训火点" in preview.inner_text(), preview.inner_text())

        # 开始模拟（无影像，scenario 驱动研判）
        page.get_by_role("button", name="火情监测", exact=True).click()
        page.get_by_role("button", name="开始模拟").click()
        page.get_by_role("button", name="机群调度").click()
        page.locator(".plan-summary").wait_for(timeout=300000)
        badge = page.locator(".task-badge").first.inner_text()
        ok &= report(12, "开始模拟→待确认", "待确认" in badge, badge)

        # 批准 → 出动推演
        page.get_by_role("button", name="机群调度").click()
        page.get_by_role("button", name="批准主方案").click()
        page.wait_for_function("document.querySelector('.task-badge')?.textContent?.includes('执行中')", timeout=30000)
        page.get_by_role("button", name="机群调度").click()
        page.locator(".sim-clock").wait_for(timeout=8000)
        ok &= report(12, "批准→出动推演", True)

        # 地图：推演相位徽章出现（随机火点位置上作业/盘旋）
        page.get_by_role("button", name="态势总览").click()
        page.locator(".tmap-drone").first.wait_for(timeout=20000)
        badges = page.evaluate("() => Array.from(document.querySelectorAll('.tmap-badge')).map(b => b.textContent).filter(Boolean)")
        ok &= report(12, "推演相位徽章", len(badges) > 0, str(badges[:5]))

        # 自动推演三路任一即通过（都在机群调度页观察——sim-clock 在 DecisionPanel，页面切走不可见）：
        # A. sim-clock 到第 2 轮（常规推进）
        # B. 提前扑灭归档（扩编压制下小火 2 轮内扑灭，round11 先例）
        # C. 演练扰动（风变/失能）在第 3 轮前触发重规划 → 任务回待确认等二次审批（产品核心卖点，FE-34/风变跨档）
        page.get_by_role("button", name="机群调度").click()
        path = ""
        try:
            page.wait_for_function(
                "(() => { const c = document.querySelector('.sim-clock')?.textContent || '';"
                " const b = document.querySelector('.task-badge')?.textContent || '';"
                " return c.includes('第 2 轮') || b.includes('已完成') || b.includes('待确认'); })()",
                timeout=90000,
            )
            clock = page.locator(".sim-clock").inner_text() if page.locator(".sim-clock").count() else ""
            badge = page.locator(".task-badge").first.inner_text()
            if "待确认" in badge:
                path = "replan"
            elif "已完成" in badge:
                path = "finish"
            else:
                path = "round2"
            ok &= report(12, "自动推演里程碑", True, f"path={path} badge={badge} clock={clock}")
        except Exception:
            raise AssertionError(f"90s 内未到达任何推演里程碑: badge={page.locator('.task-badge').inner_text()}")
        if path == "round2":
            page.get_by_placeholder("驳回/终止原因（必填）").fill("演训完成，终止")
            page.get_by_role("button", name="终止任务").click()
            page.wait_for_function("document.querySelector('.task-badge')?.textContent?.includes('已终止')", timeout=30000)
            page.wait_for_timeout(500)
        elif path == "replan":
            # 风变/失能重规划：断言方案升版（v2）后终止清理
            page.wait_for_function(
                "document.querySelector('.plan-summary')?.textContent?.includes('方案 2')", timeout=30000
            )
            ok &= report(12, "扰动重规划方案升版", True, "plan v2 已生成，等待二次审批（业务正确行为）")
            page.get_by_placeholder("驳回/终止原因（必填）").fill("演训完成，终止")
            page.get_by_role("button", name="终止任务").click()
            page.wait_for_function("document.querySelector('.task-badge')?.textContent?.includes('已终止')", timeout=30000)
            page.wait_for_timeout(500)
        ok &= report(12, "终态→推演停止", page.locator(".sim-clock").count() == 0 or path in {"finish", "replan"})

        session.assert_clean_console("round12")
        ok &= report(12, "控制台无错误", True)
        session.screenshot("round12_scenario")
    except Exception as error:
        ok = False
        detail = f"{type(error).__name__}: {str(error)[:260]}"
        session.screenshot("round12_failure")
    finally:
        session.cleanup_task()
        session.close(ok)
    if not ok:
        print("detail:", detail)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
