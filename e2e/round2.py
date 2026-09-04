"""第 2 轮：完整研判流程——上传影像、启动智能研判、生成待确认方案。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import Session, report, FRONTEND  # noqa: E402

FIRE_IMAGE = str(Path(__file__).resolve().parent / "fire.jpg")


def main() -> int:
    session = Session()
    ok = True
    detail = ""
    try:
        session.goto_app()
        session.page.get_by_text("系统运行正常").wait_for(timeout=15000)

        # 上传 fixture 影像（input 为 visually-hidden，可直接 set_input_files）
        session.page.set_input_files("input[type=file]", FIRE_IMAGE)
        session.page.get_by_text("影像已接入").wait_for(timeout=10000)
        ok &= report(2, "影像接入", True)

        # 启动智能研判（含真实环境查询，超时放宽）
        session.page.get_by_role("button", name="启动智能研判").click()
        session.page.locator(".plan-summary").wait_for(timeout=120000)
        ok &= report(2, "方案生成", True)

        # 任务状态应为"待确认"（轮询等待响应式更新）
        session.page.wait_for_function(
            "document.querySelector('.task-badge')?.textContent?.includes('待确认')",
            timeout=15000,
        )
        badge = session.page.locator(".task-badge").inner_text()
        ok &= report(2, "任务状态=待确认", "待确认" in badge, badge)

        # 方案摘要：默认火情（1800m²）按冻结公式判不可控 → 显示缺口、时间区间为 '—'（不产虚假时间窗）
        summary = session.page.locator(".plan-summary").inner_text()
        ok &= report(2, "FLP 展示", "FLP" in summary, "")
        ok &= report(2, "不可控→显示缺口", "缺口：effective_flp" in summary or "缺口：water_20l" in summary or "缺口" in summary, summary[:120].replace("\n", " "))
        window_text = summary.split("时间区间：")[1].split("分钟")[0] if "时间区间" in summary else ""
        ok &= report(2, "不可控→无时间窗", "—" in window_text, f"window={window_text!r}")
        callout = session.page.locator(".decision-callout").inner_text()
        ok &= report(2, "不可控→建议增援", "增援" in callout, callout[:80].replace("\n", " "))

        # 可控场景：small-fire fixture（260m²）→ 判可控。FLP 含真实风因子（研判默认
        # environment_mode=real，Open-Meteo 实时风随日期变化），不硬编码 FLP 值，
        # 断言摘要切换为新方案（FLP 不再是 360）且时间窗口不再是 '—'。
        session.page.get_by_role("button", name="清空并重新接入").click()
        session.page.set_input_files("input[type=file]", str(Path(__file__).resolve().parent / "small-fire.jpg"))
        session.page.get_by_text("影像已接入").wait_for(timeout=10000)
        session.page.get_by_role("button", name="启动智能研判").click()
        session.page.wait_for_function(
            "(() => { const t = document.querySelector('.plan-summary')?.textContent || '';"
            " return t.includes('FLP：') && !t.includes('FLP：360') && !t.includes('时间区间：—'); })()",
            timeout=150000,
        )
        summary2 = session.page.locator(".plan-summary").inner_text()
        window2 = summary2.split("时间区间：")[1].split("分钟")[0] if "时间区间" in summary2 else ""
        ok &= report(2, "可控→时间区间", "—" not in window2 and any(ch.isdigit() for ch in window2), f"window={window2!r}")
        callout2 = session.page.locator(".decision-callout").inner_text()
        ok &= report(2, "可控→立即处置建议", "启动" in callout2 and "增援" not in callout2, callout2[:80].replace("\n", " "))

        # 调度建议 explanation 与任务 chips
        chips = session.page.locator(".task-chips span")
        chips.first.wait_for(timeout=10000)
        ok &= report(2, "任务分工 chips", chips.count() >= 3, f"count={chips.count()}")

        # 审批按钮组出现
        approve = session.page.get_by_role("button", name="批准主方案")
        approve.wait_for(timeout=10000)
        ok &= report(2, "审批按钮组", True)

        # 无人机集群页签：机群来自后端（R1/E1...）
        session.page.get_by_role("button", name="无人机集群").click()
        session.page.get_by_text("R1").first.wait_for(timeout=10000)
        ok &= report(2, "集群 R1 展示", True)

        session.assert_clean_console("round2")
        ok &= report(2, "控制台无错误", True)
        session.screenshot("round2_plan")
    except AssertionError as error:
        ok = False
        detail = str(error)[:300]
        session.screenshot("round2_failure")
    finally:
        session.cleanup_task()
        session.close(ok)
    if not ok:
        print("detail:", detail)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
