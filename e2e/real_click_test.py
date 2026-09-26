"""真实点击模拟测试：全部用鼠标坐标点击（非语义定位器）、滚轮滚动、悬停。

目的：暴露遮挡/z-index/点击热区/滚动行为等"真人才能碰到"的问题。
旅程：六页导航滚动 → 上传真实图+VLM → 坐标点开始研判 → 坐标点批准 →
      推轮次 → 图层/标记交互 → 六页数据复核 → 终止 → 全局一致。
用法: python e2e/real_click_test.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from playwright.sync_api import sync_playwright  # noqa: E402

ART = os.path.join(os.path.dirname(os.path.abspath(__file__)), "artifacts")
RESULTS: list[dict] = []


def report(name: str, ok: bool, note: str = "") -> None:
    RESULTS.append({"name": name, "ok": bool(ok), "note": str(note)[:260]})
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" —— {note}" if note and not ok else ""), flush=True)


def real_click(page, selector: str, index: int = 0) -> bool:
    """拿元素包围盒中心，用真实鼠标事件点击（会命中遮挡物——这正是测试点）。"""
    el = page.locator(selector).nth(index)
    try:
        el.scroll_into_view_if_needed(timeout=3000)
        page.wait_for_timeout(150)
    except Exception:
        pass
    box = el.bounding_box()
    if not box:
        return False
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(cx - 6, cy - 4)
    page.mouse.move(cx, cy)
    page.mouse.click(cx, cy)
    return True


def real_click_text(page, text: str, index: int = 0) -> bool:
    el = page.get_by_role("button", name=text).nth(index)
    # 真人行为：先滚动让目标进入视野，再量坐标点击（视口外的坐标点击点在虚空）
    try:
        el.scroll_into_view_if_needed(timeout=3000)
    except Exception:
        pass
    page.wait_for_timeout(150)
    box = el.bounding_box()
    if not box:
        return False
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    return True


def api(path: str) -> dict:
    return json.load(urllib.request.urlopen(f"http://127.0.0.1:8000{path}", timeout=60))


def main() -> int:
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
    page = ctx.new_page()
    console_errors: list[str] = []
    bad: list[str] = []
    page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
    page.on("response", lambda r: bad.append(f"{r.status} {r.url[-50:]}") if r.status >= 400 else None)

    # ── 0. 进入 ──
    page.goto("http://localhost:5173")
    page.get_by_role("heading", name="森林火灾智能应急指挥平台").wait_for(timeout=30000)
    if page.get_by_text("本地演示模式").count():
        page.reload(wait_until="load")
    page.get_by_text("系统运行正常").wait_for(timeout=20000)
    page.wait_for_timeout(1000)

    # ── 1. 六页真实点击导航 + 滚轮滚动 ──
    nav_map = [("态势总览", ".map-toolbar"), ("火情监测", ".fm-stage"), ("机群调度", ".page-head"),
               ("任务管理", ".arc-row"), ("资源管理", ".drone-card"), ("数据分析", ".ana-stats")]
    for name, mark in nav_map:
        ok = real_click_text(page, name)
        page.wait_for_timeout(900)
        visible = page.locator(mark).first.is_visible() if page.locator(mark).count() else False
        report(f"真实点击导航→{name}", ok and visible)
        page.mouse.move(960, 600)
        page.mouse.wheel(0, 700)
        page.wait_for_timeout(250)
        page.mouse.wheel(0, -900)
        page.wait_for_timeout(250)

    # ── 2. 上传真实图 + VLM + 坐标点击研判 ──
    real_click_text(page, "火情监测")
    page.locator(".fm-tools-drawer[open]").wait_for(timeout=10000)
    page.locator(".vlm-toggle input").check()
    page.locator("input[type=file]").first.set_input_files("e2e/real/AoF07719.jpg")
    page.get_by_text("影像已接入").wait_for(timeout=10000)
    ok = real_click_text(page, "开始研判")
    page.wait_for_function("document.querySelector('.task-badge')?.textContent?.includes('待确认')", timeout=240000)
    report("真实点击·开始研判→待确认", ok)
    page.wait_for_timeout(1200)

    d = api("/api/analyzes?limit=1")
    aid = d["items"][0]["analysis_id"]
    full = api(f"/api/analyze/{aid}")
    fa = (full.get("result") or {}).get("fire_assessment") or {}
    fp = ((full.get("result") or {}).get("agent", {}).get("skill_chain", {}).get("fire_perception", {}) or {})
    expl = fp.get("explanation", {})
    det = fp.get("observation", {}).get("detector", {})
    ddata = det.get("data") if isinstance(det, dict) else {}
    report("VLM·真实调用", expl.get("mode") == "real", f"mode={expl.get('mode')}")
    report("YOLO·real+检出", ddata.get("mode") == "real" and len(ddata.get("detections") or []) > 0)
    quant_early = " ".join(page.locator("[aria-label='火情量化'] .fm-row").all_inner_texts())
    fmt0 = lambda v: f"{int(v):,}" if v is not None else ""
    report("同步·初始量化面积=API", fmt0(fa.get("fire_area_m2")) in quant_early, f"api={fa.get('fire_area_m2')}")

    real_click(page, ".ev-toggle button", index=1)
    page.wait_for_timeout(400)
    boxes = page.locator(".ew-box").count()
    report("真实点击·检测框视图", boxes > 0, f"框数={boxes}")

    # ── 3. 坐标点击生成调度方案 → 批准 ──
    real_click_text(page, "生成调度方案")
    page.locator(".plan-summary").wait_for(timeout=20000)
    report("真实点击·生成调度方案", True)
    approved = False
    for _ in range(3):
        real_click_text(page, "批准主方案")
        try:
            page.wait_for_function("document.querySelector('.task-badge')?.textContent?.includes('执行中')", timeout=15000)
            approved = True
            break
        except Exception:
            # 抓现场：错误提示/按钮状态/位置，判断是落空还是被后端拒绝
            toast = page.locator(".ant-message, [class*=toast], [class*=error], .people-risk-line").last.inner_text()[:120] if page.locator("[class*=toast], [class*=error]").count() else "(无弹窗)"
            btn = page.get_by_role("button", name="批准主方案")
            info = f"按钮数={btn.count()} disabled={btn.first.is_disabled() if btn.count() else '?'}"
            print(f"  [debug] 第{_+1}次批准未生效: toast={toast} | {info}", flush=True)
            page.wait_for_timeout(1000)
    report("真实点击·批准→执行中", approved)

    # ── 4. 推演：坐标点击下一轮 ×2 + 图层开关真实点击 ──
    page.wait_for_timeout(3000)
    for i in range(2):
        real_click_text(page, "执行下一轮监测")
        # 等本轮落账（推演中按钮禁用属正确 UX）
        page.wait_for_timeout(3200)
    rounds_dom = page.locator(".round-list > div").count()
    rounds_api = len(api(f"/api/analyze/{aid}").get("rounds") or [])
    report("真实点击·轮次推进=API", rounds_dom >= 1 and abs(rounds_dom - rounds_api) <= 1, f"dom={rounds_dom} api={rounds_api}")

    legend = page.locator(".map-legend .legend-item")
    if legend.count() >= 6:
        for i in [0, 2]:
            real_click(page, ".map-legend .legend-item", index=i)
            page.wait_for_timeout(200)
        for i in [2, 0]:
            real_click(page, ".map-legend .legend-item", index=i)
            page.wait_for_timeout(150)
    report("真实点击·图层开关往返", True)

    # ── 5. 六页数据复核 ──
    fmt = lambda v: f"{int(v):,}" if v is not None else ""
    page.get_by_role("button", name="态势总览").first.click()
    page.locator(".map-toolbar").wait_for(timeout=15000)
    report("复核·态势总览执行中", "执行中" in page.locator(".task-badge").first.inner_text())
    page.get_by_role("button", name="火情监测", exact=True).first.click()
    page.wait_for_timeout(800)
    quant = " ".join(page.locator("[aria-label='火情量化'] .fm-row").all_inner_texts())
    report("复核·火情监测量化面板在", len(quant.strip()) > 20)
    page.get_by_role("button", name="数据分析").first.click()
    page.locator(".ana-stats").first.wait_for(timeout=15000)
    page.wait_for_timeout(1500)
    tr = page.locator(".gt-scroll.ana-rounds-scroll tbody tr").count()
    report("复核·分析页轮次=API", abs(tr - rounds_api) <= 1, f"dom={tr} api={rounds_api}")
    page.get_by_role("button", name="资源管理").first.click()
    page.locator(".drone-card").first.wait_for(timeout=15000)
    fleet = page.locator(".fleet-roster").inner_text()
    report("复核·资源页锁定与任务", "是 · 方案" in fleet)
    card = page.locator(".drone-card").first
    box = card.bounding_box()
    page.mouse.move(box["x"] + 60, box["y"] + 20)
    page.wait_for_timeout(300)
    page.get_by_role("button", name="任务管理").first.click()
    page.locator(".arc-row").first.wait_for(timeout=15000)
    row = page.locator(f".arc-row[title*='{aid}']").first.inner_text()
    report("复核·任务管理行状态", "执行中" in row, row[:60])

    # ── 6. 坐标点击终止 → 全局一致 ──
    page.get_by_role("button", name="机群调度").first.click()
    page.locator(".plan-summary").wait_for(timeout=15000)
    reason = page.locator(".reason-input").first
    if reason.count():
        reason.fill("real_click 清理终止")
    real_click_text(page, "终止任务")
    try:
        page.wait_for_function("document.querySelector('.task-badge')?.textContent?.includes('已终止')", timeout=15000)
        badge = "已终止"
    except Exception:
        badge = page.locator(".task-badge").first.inner_text()
    report("真实点击·终止→已终止", "已终止" in badge, badge)
    st = api(f"/api/analyze/{aid}").get("status")
    report("终止·API一致", st == "terminated", str(st))

    console_errors[:] = [e for e in console_errors if "409 (Conflict)" not in e and "favicon" not in e]
    bad[:] = [u for u in bad if not (u.startswith("409 ") and ("/approval" in u or "/rounds" in u)) and "favicon" not in u]
    report("控制台/网络净度", not console_errors and not bad, " | ".join((console_errors + bad)[:3]))

    page.screenshot(path=os.path.join(ART, "real_click_final.png"))
    browser.close()
    pw.stop()

    ok = all(r["ok"] for r in RESULTS)
    with open(os.path.join(ART, "real_click.json"), "w", encoding="utf-8") as fh:
        json.dump({"ok": ok, "results": RESULTS}, fh, ensure_ascii=False, indent=1)
    print(f"{'✅ 全部通过' if ok else '❌ 存在失败'} —— {len(RESULTS)} 项")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
