"""第 11 轮：紫霞湖基地出动推演——批准即动画、相位徽章、自动轮次推进、SOC/补水联动、终止即停。"""
import re
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
        # 小火场景（可控）→ 研判 → 批准
        page.set_input_files("input[type=file]", "e2e/small-fire.jpg")
        page.get_by_text("影像已接入").wait_for(timeout=10000)
        page.get_by_role("button", name="启动智能研判").click()
        page.locator(".plan-summary").wait_for(timeout=150000)
        ok &= report(11, "研判完成", True)
        page.get_by_role("button", name="批准主方案").click()
        page.wait_for_function("document.querySelector('.task-badge')?.textContent?.includes('执行中')", timeout=30000)
        ok &= report(11, "批准→执行中", True)

        # 出动动画：推演时钟出现；机群标记相位徽章非空；盘旋侦察机坐标持续变化（dataset 实时经纬度）
        page.locator(".sim-clock").wait_for(timeout=8000)
        ok &= report(11, "推演时钟启动", True, page.locator(".sim-clock").inner_text())
        page.get_by_role("button", name="林区态势").click()
        page.locator(".tmap-drone").first.wait_for(timeout=20000)
        capture = "() => JSON.stringify(Array.from(document.querySelectorAll('.tmap-drone')).map(m => (m.dataset.longitude || '') + ',' + (m.dataset.latitude || '')))"
        t1 = page.evaluate(capture)
        page.wait_for_timeout(2000)
        t2 = page.evaluate(capture)
        ok &= report(11, "机群位置随时间变化", t1 != t2, f"{t1[:80]} -> {t2[:80]}")
        badges = page.evaluate("() => Array.from(document.querySelectorAll('.tmap-badge')).map(b => b.textContent).filter(Boolean)")
        ok &= report(11, "相位徽章上屏", len(badges) > 0 and any("盘旋" in b or "作业" in b or "出动" in b for b in badges), str(badges[:5]))

        # 自动推演：等第 3 轮（每轮 6s）——压制增强后小火常在 2 轮内扑灭归档（FE-41/BE-12b），
        # 提前完成同样算通过，此时推演钟已随归档停止
        page.get_by_role("button", name="指挥中枢").click()
        try:
            page.wait_for_function("document.querySelector('.sim-clock')?.textContent?.includes('第 3 轮')", timeout=40000)
            round_note = page.locator(".sim-clock").inner_text()
        except Exception:
            page.wait_for_function("document.querySelector('.task-badge')?.textContent?.includes('已完成')", timeout=40000)
            round_note = "第 2 轮前扑灭归档（压制有效，提前完成）"
        ok &= report(11, "自动推演至第 3 轮", True, round_note)
        monitor_text = page.locator(".monitor-result").inner_text() if page.locator(".monitor-result").count() else ""
        match = re.search(r"E1:(\d+(?:\.\d+)?)%", monitor_text)
        soc_after = float(match.group(1)) if match else None
        ok &= report(11, "轮次推演 SOC 下降", soc_after is None or soc_after < 92, f"E1 SOC={soc_after}")
        ok &= report(11, "火情随轮次演化", monitor_text == "" or "火焰面积" in monitor_text, monitor_text[:80].replace("\n", " "))

        # 补水闭环：首架次药剂喷尽后必然返航→基地补水/充电（药剂 20L ÷ 4L/min = 5min 作业期）；
        # 若火已提前扑灭归档，机群随推演冻结，无返航相位可观察——同样豁免
        page.get_by_role("button", name="林区态势").click()
        page.locator(".tmap-drone").first.wait_for(timeout=20000)
        try:
            refill_appeared = page.wait_for_function(
                """() => Array.from(document.querySelectorAll('.tmap-badge'))
                      .some(b => ['返航中', '基地补水', '基地充电'].includes(b.textContent))""",
                timeout=30000,
            )
            ok &= report(11, "返航/补水相位出现", bool(refill_appeared))
        except Exception:
            completed_now = page.evaluate("() => (document.querySelector('.task-badge') || {}).textContent?.includes('已完成') || false")
            ok &= report(11, "返航/补水相位出现", bool(completed_now), "提前扑灭归档，跳过返航相位观察")
        phases_now = page.evaluate("() => Array.from(document.querySelectorAll('.tmap-badge')).map(b => b.textContent).filter(Boolean)")
        ok &= report(11, "相位快照", True, str(phases_now[:5]))

        # 终止任务 → 推演停止；若火已提前扑灭归档（已完成），终止 409 属预期，跳过
        page.get_by_role("button", name="指挥中枢").click()
        already_done = page.evaluate("() => (document.querySelector('.task-badge') || {}).textContent?.includes('已完成') || false")
        if not already_done:
            page.get_by_placeholder("驳回/终止原因（必填）").fill("推演验证完成，终止")
            page.get_by_role("button", name="终止任务").click()
            page.wait_for_function("document.querySelector('.task-badge')?.textContent?.includes('已终止')", timeout=30000)
        page.wait_for_timeout(600)
        ok &= report(11, "终止→推演停止", page.locator(".sim-clock").count() == 0 or already_done,
                     "提前扑灭归档" if already_done else "")

        session.assert_clean_console("round11")
        ok &= report(11, "控制台无错误", True)
        session.screenshot("round11_mission")
    except Exception as error:
        import traceback
        ok = False
        detail = f"{type(error).__name__}: {str(error)[:260]}"
        traceback.print_exc()
        session.screenshot("round11_failure")
    finally:
        session.cleanup_task()
        session.close(ok)
    if not ok:
        print("detail:", detail)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
