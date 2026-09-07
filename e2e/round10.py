"""第 10 轮：高德真实卫星地图专项——底图激活、真实水源精准标注、取水路线、图层开关、联动与光标经纬度。"""
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import Session, report  # noqa: E402


def preheat_environment(attempts: int = 3) -> dict:
    """预热环境缓存并重试（Overpass 镜像偶发慢/超时；partial 结果已不写缓存），返回带水源的信封。"""
    last: dict = {}
    for _ in range(attempts):
        req = urllib.request.Request(
            "http://127.0.0.1:8000/api/environment?latitude=32.0725&longitude=118.8415&environment_mode=real"
        )
        with urllib.request.urlopen(req, timeout=120) as response:
            last = json.loads(response.read().decode())
        if last.get("water_sources"):
            return last
    return last


def main() -> int:
    session = Session()
    ok = True
    detail = ""
    page = session.page
    try:
        env = preheat_environment()
        real_water_count = len(env.get("water_sources", []))
        ok &= report(10, "真实水源数据(Overpass 镜像回退)", real_water_count > 0, f"count={real_water_count}")

        session.goto_app()
        page.get_by_role("button", name="林区态势").click()
        # AMap 分支激活：卫星地图容器存在（SVG 回退分支 .large-map 不应出现）
        page.locator(".tactical-amap").wait_for(timeout=20000)
        ok &= report(10, "高德底图激活", page.locator(".large-map").count() == 0)
        # 低倍默认视图：缩放联动减负，仅首选水源可见（FE-15）
        page.locator(".tmap-water.preferred").wait_for(timeout=30000)
        low_count = page.locator(".tmap-water:visible").count()
        ok &= report(10, "低倍视图仅首选水源", low_count == 1, f"visible={low_count}")
        # 放大后全部水源展开（双击放大，每次 +1 级，躲开标记的空白区）
        box = page.locator(".tactical-amap").bounding_box()
        tx, ty = box["x"] + box["width"] * 0.18, box["y"] + box["height"] * 0.22
        for _ in range(3):
            page.mouse.dblclick(tx, ty)
            page.wait_for_timeout(700)
        page.wait_for_function(
            f"document.querySelectorAll('.tmap-water').length >= {real_water_count} && "
            "Array.from(document.querySelectorAll('.tmap-water')).every(el => el.offsetParent !== null)",
            timeout=20000,
        )
        ok &= report(10, "真实水源标注", True, f"markers={real_water_count}")

        preferred = page.locator(".tmap-water.preferred")
        preferred.wait_for(timeout=10000)
        pref_text = preferred.inner_text()
        ok &= report(10, "首选水源高亮(紫霞湖)", "紫霞湖" in pref_text, pref_text.replace("\n", " "))

        route = page.locator(".tmap-route-label.water")
        route.wait_for(timeout=10000)
        route_text = route.inner_text()
        ok &= report(10, "取水路线虚线标注", "取水路线" in route_text and "m" in route_text, route_text)

        fire = page.locator(".tmap-fire")
        fire.wait_for(timeout=10000)
        ok &= report(10, "火点标注", "火点中心" in fire.inner_text())

        drones = page.locator(".tmap-drone").count()
        ok &= report(10, "无人机标记 12 架", drones == 12, f"drones={drones}")

        # 光标经纬度读数（高德模式下 GCJ→WGS 反算）；需多步移动才触发 AMap mousemove
        box = page.locator(".tactical-amap").bounding_box()
        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        page.mouse.move(cx - 120, cy - 80)
        page.mouse.move(cx, cy, steps=6)
        page.wait_for_function(
            "document.querySelector('.map-coords')?.textContent?.includes('°E')", timeout=10000
        )
        ok &= report(10, "光标经纬度读数", True, page.locator(".map-coords").inner_text())

        # 图层开关（浮层已修复为 wrap 层，高德模式下可用）：关闭水源层 → 标记隐藏
        legend_water = page.locator(".map-legend .legend-item", has_text="水源")
        legend_water.click()
        page.wait_for_function(
            "Array.from(document.querySelectorAll('.tmap-water')).every(el => el.offsetParent === null)",
            timeout=5000,
        )
        ok &= report(10, "图层开关隐藏水源", True)
        legend_water.click()
        page.locator(".tmap-water").first.wait_for(state="visible", timeout=5000)
        ok &= report(10, "图层开关恢复水源", True)

        # 右侧栏水源清单行点击 → 联动定位 + 详情卡（人话标题 + 真实 GPS 坐标）
        page.locator(".map-side-rail .water-row").nth(1).click()
        page.locator(".marker-detail").wait_for(timeout=5000)
        head = page.locator(".marker-detail-head").inner_text()
        body = page.locator(".marker-detail-body").inner_text()
        ok &= report(10, "清单联动详情卡", "water-" not in head and "°E" in body,
                     (head + " | " + body).replace("\n", " ")[:120])

        # 演示模式水源 GPS 精准标注（scene.json latitude/longitude 契约）
        page.get_by_role("button", name="指挥中枢").click()
        page.locator(".environment-controls select").select_option("demo")
        page.wait_for_function(
            "document.querySelector('.environment-meta')?.textContent?.includes('demo-data')", timeout=15000
        )
        page.get_by_role("button", name="林区态势").click()
        demo_water = page.locator(".tmap-water", has_text="北侧蓄水池")
        demo_water.wait_for(timeout=15000)
        demo_route = page.locator(".tmap-route-label.water")
        demo_route.wait_for(timeout=10000)
        ok &= report(10, "演示模式水源 GPS 标注", True, demo_route.inner_text())

        session.assert_clean_console("round10")
        ok &= report(10, "控制台无错误", True)
        session.screenshot("round10_amap")
    except AssertionError as error:
        ok = False
        detail = str(error)[:300]
        session.screenshot("round10_failure")
    finally:
        session.cleanup_task()
        session.close(ok)
    if not ok:
        print("detail:", detail)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
