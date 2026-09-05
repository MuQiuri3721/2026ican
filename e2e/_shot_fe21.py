import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import Session

s = Session()
try:
    s.goto_app()
    page = s.page
    page.get_by_role("button", name="林区态势").click()
    page.locator(".tactical-amap").wait_for(timeout=20000)
    page.locator(".tmap-fire").wait_for(timeout=15000)
    time.sleep(3)
    box = page.locator(".tactical-map-wrap").bounding_box()
    # 火点居中，光晕在两帧间的半径差可见
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.screenshot(path="e2e/artifacts/fe21_halo_a.png",
                    clip={"x": cx - 240, "y": cy - 170, "width": 480, "height": 340})
    time.sleep(0.55)
    page.screenshot(path="e2e/artifacts/fe21_halo_b.png",
                    clip={"x": cx - 240, "y": cy - 170, "width": 480, "height": 340})
    # 工具栏(语音开关 + 来源标注在指挥中枢,分开截)
    page.get_by_role("button", name="指挥中枢").click()
    page.locator(".src-note").wait_for(timeout=30000)
    page.screenshot(path="e2e/artifacts/fe21_srcnote.png", full_page=False)
    print("shots ok")
finally:
    s.close(True)
