"""第 17 轮：地图选点指定火点坐标（模拟发现火情）→ 坐标联动环境/等高线/上传面板。

前置：amap 分支（VITE_AMAP_KEY 已配置）。断言点：选点按钮、选点态、
地图点击后状态栏坐标变化、日志记录、上传面板坐标提示同步。
"""
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

        session.page.get_by_role("button", name="林区态势").click()
        session.page.wait_for_selector(".tactical-amap", timeout=20000)

        pick_btn = session.page.get_by_role("button", name="指定火点")
        pick_btn.wait_for(timeout=8000)
        ok &= report(17, "指定火点按钮存在", pick_btn.count() > 0)

        tag = session.page.locator(".map-toolbar-tools .status-tag")
        init_text = tag.inner_text()

        pick_btn.click()
        ok &= report(17, "选点模式开启", pick_btn.get_attribute("aria-pressed") == "true")

        box = session.page.locator(".tactical-amap").bounding_box()
        # 偏左下点击，避开中央火点与机群标记；挂捕获探针以便失败时留证
        session.page.evaluate("""() => {
            window.__pickEv = [];
            const el = document.querySelector('.tactical-amap');
            el.addEventListener('mouseup', (e) => {
                window.__pickEv.push([e.clientX, e.clientY, e.target.tagName,
                    (e.target.className || '').toString().slice(0, 40)]);
            }, true);
        }""")
        session.page.mouse.click(box["x"] + box["width"] * 0.30, box["y"] + box["height"] * 0.35)
        session.page.wait_for_timeout(1800)
        probe = session.page.evaluate("window.__pickEv || []")

        new_text = tag.inner_text()
        ok &= report(17, "选点后坐标联动", new_text != init_text,
                     f"{init_text.strip()} → {new_text.strip()} probe={probe[-1] if probe else '无mouseup!'}")
        ok &= report(17, "选点模式自动退出", pick_btn.get_attribute("aria-pressed") == "false")

        # 上传面板的火点定位提示应与选点坐标同步（回到指挥中枢页签）
        session.page.get_by_role("button", name="指挥中枢").click()
        note = session.page.locator(".fire-coord-note")
        note.wait_for(timeout=8000)
        note_text = note.inner_text()
        lng = new_text.split("°E")[0].strip().split()[-1]
        ok &= report(17, "上传面板坐标同步", lng in note_text, note_text[:60])

        session.assert_clean_console("round17")
        ok &= report(17, "控制台无错误", True)
        session.screenshot("round17_pick")
    except AssertionError as error:
        ok = False
        detail = str(error)[:300]
        session.screenshot("round17_failure")
    finally:
        session.cleanup_task()
        session.close(ok)
    if not ok:
        print("detail:", detail)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
