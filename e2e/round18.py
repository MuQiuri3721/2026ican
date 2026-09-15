"""第 18 轮：推演回放面板（FE-67 复盘层）——逐轮快照回放、播放推进、机群快照格。"""
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

        # 生成随机火情 → 开始模拟 → 批准（与 round12 同链路）
        page.get_by_role("button", name="生成随机火情").click()
        page.locator(".scenario-facts").wait_for(timeout=8000)
        page.get_by_role("button", name="开始模拟").click()
        page.locator(".plan-summary").wait_for(timeout=150000)
        page.get_by_role("button", name="批准主方案").click()
        page.wait_for_function("document.querySelector('.task-badge')?.textContent?.includes('执行中')", timeout=30000)

        # 自动推演至第 2 轮（sim-clock 是本地时钟会超前于 rounds 数据，等回放刻度 ≥2 才是数据落位）
        page.wait_for_function("document.querySelector('.sim-clock')?.textContent?.includes('第 2 轮')", timeout=40000)

        # 回放面板存在且展开（长面板内 sticky 表头会拦截 actionability 点击，用 evaluate click）
        panel = page.locator(".replay-panel")
        panel.wait_for(timeout=10000)
        page.evaluate("document.querySelector('.replay-head').click()")
        page.locator(".replay-body").wait_for(timeout=5000)
        page.wait_for_function("document.querySelectorAll('.replay-ticks .tick').length >= 2", timeout=60000)
        ok &= report(18, "回放面板展开", True)

        # KPI 行：FLP before → after 与净变化
        kpis = page.locator(".replay-kpis").inner_text()
        ok &= report(18, "回放 KPI 账本", "FLP before → after" in kpis and "净变化" in kpis, kpis[:110].replace("\n", " "))

        # 播放：点击播放后自动推进到第 2 轮
        page.evaluate("document.querySelector('.replay-btn.play').click()")
        page.wait_for_function(
            "document.querySelector('.replay-pos')?.textContent?.includes('第 2 /')", timeout=10000
        )
        ok &= report(18, "播放自动推进", True, page.locator(".replay-pos").inner_text())

        # 机群快照格：12 架全量呈现（SOC/相位/药剂）
        fleet_rows = page.locator(".replay-fleet .rf").count()
        ok &= report(18, "机群快照格", fleet_rows >= 12, f"rows={fleet_rows}")

        # 轮次刻度点与轮数一致
        ticks = page.locator(".replay-ticks .tick").count()
        ok &= report(18, "轮次刻度", ticks >= 2, f"ticks={ticks}")

        session.assert_clean_console("round18")
        ok &= report(18, "控制台无错误", True)
        session.screenshot("round18_replay")
    except Exception as error:
        ok = False
        detail = f"{type(error).__name__}: {str(error)[:260]}"
        session.screenshot("round18_failure")
    finally:
        session.cleanup_task()
        session.close(ok)
    if not ok:
        print("detail:", detail)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
