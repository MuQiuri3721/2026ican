"""第 19 轮：多任务对比看板（FE-68）——历史行勾选、对比表渲染、指标齐全。"""
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
        # 自建 2 条可对比任务（离线研判，scenario 驱动 FLP）
        ids = []
        for index in range(2):
            body = session.api("POST", "/api/analyze", {
                "scene_id": "forest-demo-01", "image_name": f"round19-{index}.jpg",
                "environment_mode": "offline", "people_status": "absent",
                "scenario": {"fire_origin": {"x": 200, "y": 200}, "fire_area_m2": 300 + index * 200, "growth_rate": 0.2},
            })
            ids.append(body["analysis_id"])

        session.goto_app()
        session.page.get_by_text("系统运行正常").wait_for(timeout=15000)
        session.page.get_by_role("tab", name="历史任务").click()
        session.page.locator(".history-row").first.wait_for(timeout=15000)

        # 勾选 2 个任务（真实 input 可点，FE-49 教训）→「对比所选」出现
        boxes = page.locator(".cmp-pick input")
        boxes.nth(0).check()
        boxes.nth(1).check()
        compare_btn = page.get_by_role("button", name="对比所选（2）")
        compare_btn.wait_for(timeout=5000)
        compare_btn.click()
        ok &= report(19, "勾选与对比入口", True)

        # 对比表渲染：三态结论/初始/最终/净变化行 + 2 个任务列
        page.locator(".compare-panel .compare-table").wait_for(timeout=10000)
        table_text = page.evaluate("document.querySelector('.compare-panel .compare-table').textContent")
        cols = page.locator(".compare-panel thead th").count()
        ok &= report(19, "对比表渲染", cols >= 3, f"th={cols}")
        ok &= report(19, "指标行齐全",
                     all(key in table_text for key in ("三态结论", "初始 FLP", "最终 FLP", "净变化", "耗水")),
                     str(all(key in table_text for key in ("三态结论", "初始 FLP", "最终 FLP", "净变化", "耗水"))))

        # 勾选变化联动：取消一个 → 面板收起
        boxes.nth(1).uncheck()
        page.wait_for_function("!document.querySelector('.compare-panel')", timeout=5000)
        ok &= report(19, "取消勾选联动收起", True)

        session.assert_clean_console("round19")
        ok &= report(19, "控制台无错误", True)
        session.screenshot("round19_compare")
    except Exception as error:
        ok = False
        detail = f"{type(error).__name__}: {str(error)[:260]}"
        session.screenshot("round19_failure")
    finally:
        session.cleanup_task()
        session.close(ok)
    if not ok:
        print("detail:", detail)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
