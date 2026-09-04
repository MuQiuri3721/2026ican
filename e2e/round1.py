"""第 1 轮：应用加载、服务在线、真实紫金山等高线渲染、地图标记与比例尺。

分支自适应：VITE_AMAP_KEY 配置且加载成功时走高德卫星分支（TacticalMap），
否则走 SVG 示意图回退分支，两组断言等价。
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
        ok &= report(1, "服务在线", True)

        # 等高线与标记都在"林区态势"视图，先切页签
        session.page.get_by_role("button", name="林区态势").click()
        session.page.wait_for_selector(".tactical-amap, .large-map", timeout=20000)
        amap_mode = session.page.locator(".tactical-amap").count() > 0
        ok &= report(1, "地图分支", True, "amap" if amap_mode else "svg-fallback")

        if amap_mode:
            # 高德分支：等高线来源浮层（wrap 层，两种模式共用）
            session.page.wait_for_function(
                "document.querySelector('.map-source')?.textContent?.includes('N32E118.hgt')",
                timeout=30000,
            )
            ok &= report(1, "等高线来源", True, session.page.locator(".map-source").inner_text())

            # 真实 DEM 等高线海拔标签（AMap Marker 内容）
            session.page.wait_for_function(
                "document.querySelectorAll('.tmap-contour-label').length > 0", timeout=30000
            )
            labels = session.page.locator(".tmap-contour-label")
            label_values = [labels.nth(i).text_content() or "" for i in range(min(labels.count(), 5))]
            ok &= report(1, "等高线海拔标签", len(label_values) > 0, f"labels={label_values}")

            fire = session.page.locator(".tmap-fire")
            fire.wait_for(timeout=15000)
            ok &= report(1, "火点标注", "火点中心" in fire.inner_text(), fire.inner_text())
            drones = session.page.locator(".tmap-drone").count()
            ok &= report(1, "机群标记>=8", drones >= 8, f"drones={drones}")

            scale = session.page.locator(".amap-scalecontrol")
            scale.wait_for(timeout=8000)
            scale_text = scale.inner_text()
            ok &= report(1, "比例尺", any(t in scale_text for t in ("公里", "米", "m")), scale_text)
        else:
            note = session.page.locator(".contour-note")
            note.wait_for(timeout=20000)
            # 轮询等待真实 DEM 数据到达（onMounted 并发请求存在时序竞争）
            session.page.wait_for_function(
                "document.querySelector('.contour-note small')?.textContent?.includes('N32E118.hgt')",
                timeout=30000,
            )
            source = note.locator("small").inner_text()
            ok &= report(1, "等高线来源", source == "N32E118.hgt", f"source={source}")
            interval = note.locator("b").inner_text()
            ok &= report(1, "等高距 20m", interval.strip() == "20 m", f"interval={interval}")

            session.page.wait_for_function(
                "document.querySelectorAll('.contour-line').length > 0", timeout=20000
            )
            contour_count = session.page.locator(".contour-line").count()
            ok &= report(1, "等高线渲染", contour_count > 0, f"paths={contour_count}")

            labels = session.page.locator(".contour-label")
            labels.first.wait_for(timeout=15000)
            # SVG <text> 元素不支持 inner_text，使用 text_content
            label_values = [labels.nth(i).text_content() or "" for i in range(labels.count())]
            ok &= report(1, "等高线海拔标签", len(label_values) > 0, f"labels={label_values}")

            fire = session.page.locator(".map-node.fire")
            fire.wait_for(timeout=15000)
            fire_label = fire.inner_text()
            ok &= report(1, "火点标注 GPS", "118.8432" in fire_label, f"label={fire_label!r}")
            nodes = session.page.locator(".map-node").count()
            ok &= report(1, "地图标记数(火+机群)>=9", nodes >= 9, f"nodes={nodes}")

            scale = session.page.locator(".map-scale b")
            scale.wait_for(timeout=5000)
            ok &= report(1, "比例尺", "m" in scale.inner_text(), scale.inner_text())

        session.assert_clean_console("round1")
        ok &= report(1, "控制台无错误", True)
        session.screenshot("round1_map")
    except AssertionError as error:
        ok = False
        detail = str(error)[:300]
        session.screenshot("round1_failure")
    finally:
        session.cleanup_task()
        session.close(ok)
    if not ok:
        print("detail:", detail)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
