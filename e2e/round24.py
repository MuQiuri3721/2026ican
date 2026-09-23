"""第 24 轮：FE-84/85 新 UI 面专项——数据分析页、任务管理详情、资源总览 KPI、
机群调度轮次条、火情监测趋势分析条、态势总览环形图/风向标。
只读断言（不创建任务、不上传影像），可安全并入全量跑批。"""
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
        page.get_by_text("系统运行正常").wait_for(timeout=20000)

        # —— 态势总览：环形进度 / 图例 / 风向标（FE-85 第二波新增）——
        # goto_app 统一导航落在火情监测页，先切回态势总览
        page.get_by_role("button", name="态势总览").click()
        page.locator(".fm-donut").wait_for(timeout=10000)
        ok &= report(24, "任务执行环形图", True)
        page.locator(".map-wind-indicator").wait_for(timeout=15000)
        ok &= report(24, "风向指示标", "风向" in page.locator(".map-wind-indicator").inner_text())

        # —— 火情监测：趋势分析条（演化 + 图像时序空态/数据态二选一）——
        page.get_by_role("button", name="火情监测").click()
        page.locator(".trend-panel").wait_for(timeout=10000)
        ok &= report(24, "趋势分析条", "趋势分析" in page.locator(".trend-panel .panel-heading").inner_text())

        # —— 机群调度：地图 + 机群编组三组表 + 轮次与重规划条 ——
        page.get_by_role("button", name="机群调度").click()
        page.locator(".dispatch-grid2").wait_for(timeout=10000)
        groups = page.locator(".dispatch-grid2 .group-table-card").count()
        ok &= report(24, "机群编组三组表", groups == 3, f"groups={groups}")
        page.locator(".round-bar").wait_for(timeout=10000)
        ok &= report(24, "轮次与重规划条", "轮次与重规划" in page.locator(".round-bar .rb-title").inner_text())

        # —— 资源管理：资源总览八卡 + 12 张无人机卡 + 物资库/水源表 ——
        page.get_by_role("button", name="资源管理").click()
        page.locator(".res-kpis").wait_for(timeout=10000)
        kpis = page.locator(".res-kpis .res-kpi").count()
        ok &= report(24, "资源总览 KPI 八卡", kpis == 8, f"kpis={kpis}")
        page.wait_for_function(
            "document.querySelectorAll('.drone-card').length === 12", timeout=15000
        )
        ok &= report(24, "无人机卡片网格", True)
        ok &= report(24, "物资库表", page.locator(".inv-panel .data-table").count() == 1)

        # —— 任务管理：列表 + 行内「详情」按钮拉取右侧详情面板 ——
        page.get_by_role("button", name="任务管理").click()
        page.locator(".history-row").first.wait_for(timeout=15000)
        page.locator(".history-row .hr-detail").first.click()
        page.locator(".history-detail .hd-head").wait_for(timeout=15000)
        ok &= report(24, "任务详情面板", "任务详情" in page.locator(".history-detail .hd-head").inner_text())

        # —— 数据分析（FE-84 新页）：指标卡 / 报告输出 / 多任务对比 ——
        page.get_by_role("button", name="数据分析").click()
        page.locator(".analysis-grid").wait_for(timeout=10000)
        ok &= report(24, "当前任务分析四指标卡", page.locator(".ana-stats .ana-stat").count() == 4)
        outputs = page.locator(".report-output .report-out-btn").count()
        ok &= report(24, "报告输出四按钮", outputs == 4, f"outputs={outputs}")
        page.locator(".ana-pick label").first.wait_for(timeout=15000)
        ok &= report(24, "多任务对比勾选列表", page.locator(".ana-pick label").count() >= 1)

        session.assert_clean_console("round24")
        ok &= report(24, "控制台无错误", True)
        session.screenshot("round24_new_ui")
    except Exception as error:
        ok = False
        detail = f"{type(error).__name__}: {str(error)[:260]}"
        session.screenshot("round24_failure")
    finally:
        session.cleanup_task()
        session.close(ok)
    if not ok:
        print("detail:", detail)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
