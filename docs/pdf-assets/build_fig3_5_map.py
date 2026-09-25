# -*- coding: utf-8 -*-
"""图3-5 底图采集 v2：上传 1800㎡ 标准火情影像 → 研判 → 批准 → 推演 → 放大截战术地图。
从项目根运行：python docs/pdf-assets/build_fig3_5_map.py
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "fig3-5-map.png"

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1720, "height": 980}, device_scale_factor=2)
    pg.goto("http://localhost:5173/")
    pg.wait_for_timeout(7000)
    # 上传标准火情影像（1800㎡，II 级）
    pg.get_by_role("button", name="火情监测", exact=True).click()
    pg.wait_for_timeout(1500)
    # 切演示数据模式（fixture 1800㎡ II 级场景，12 架环形展开示意）
    pg.evaluate("document.querySelector('.fm-env-controls').open = true")
    pg.locator(".environment-controls select").select_option("demo")
    pg.wait_for_timeout(2500)
    pg.set_input_files("input[type=file]", str(ROOT / "e2e" / "_real_images" / "fire1.jpg"))
    pg.get_by_text("影像已接入").wait_for(timeout=15000)
    pg.get_by_role("button", name="开始研判").click()
    pg.wait_for_timeout(20000)
    # 等研判完成（批准按钮出现）——不批准，保持 1800㎡ 火点 + 12 架展开 + 取水路线的示意状态
    pg.wait_for_function("""() => Array.from(document.querySelectorAll('button')).some(b => b.textContent.includes('批准主方案'))""", timeout=180000)
    pg.get_by_role("button", name="态势总览", exact=True).click()
    pg.locator(".tactical-amap").wait_for(timeout=30000)
    pg.wait_for_timeout(4000)
    # dblclick 放大（round10 验证坐标：18%/22% 处避开标记与道路要素，每次 +1 级）
    box = pg.locator(".tactical-amap").bounding_box()
    tx, ty = box["x"] + box["width"] * 0.18, box["y"] + box["height"] * 0.22
    for _ in range(4):
        pg.mouse.dblclick(tx, ty)
        pg.wait_for_timeout(1200)
    pg.wait_for_timeout(2500)
    el = pg.locator(".tactical-amap")
    el.screenshot(path=str(OUT))
    print("captured", OUT)
    b.close()
