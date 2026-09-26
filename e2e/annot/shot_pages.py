"""演示视频配图截图脚本：创建完整演示数据 → 逐页截图 → 抓取标注目标包围盒。

产出: e2e/artifacts/annot/shots/*.png + ../boxes.json
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from playwright.sync_api import sync_playwright  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shots")
os.makedirs(OUT, exist_ok=True)


def api(path: str, payload=None) -> dict:
    if payload is None:
        return json.load(urllib.request.urlopen(f"http://127.0.0.1:8000{path}", timeout=60))
    req = urllib.request.Request(f"http://127.0.0.1:8000{path}", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    return json.load(urllib.request.urlopen(req, timeout=120))


def shot(page, name: str, boxes: dict, annotations: list, to_top: bool = True):
    if to_top:
        page.evaluate("() => { const m = document.querySelector('main'); if (m) m.scrollTop = 0; window.scrollTo(0, 0); }")
        page.wait_for_timeout(350)
    picked = []
    for n, sel, idx, label in annotations:
        el = page.locator(sel).nth(idx) if idx is not None else page.locator(sel).first
        if not el.count():
            continue
        try:
            b = el.bounding_box()
        except Exception:
            b = None
        if not b or b["y"] + b["height"] < 0 or b["y"] > 1078:
            continue
        picked.append({"n": n, "label": label,
                       "cx": round(b["x"] + b["width"] / 2), "cy": round(b["y"] + b["height"] / 2),
                       "w": round(b["width"]), "h": round(b["height"])})
    page.screenshot(path=os.path.join(OUT, f"{name}.png"))
    boxes[name] = picked
    print(f"  {name}: {len(picked)} 个标注", flush=True)


def main() -> None:
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
    page = ctx.new_page()
    page.goto("http://localhost:5173")
    page.get_by_role("heading", name="森林火灾智能应急指挥平台").wait_for(timeout=30000)
    if page.get_by_text("本地演示模式").count():
        page.reload(wait_until="load")
    page.get_by_text("系统运行正常").wait_for(timeout=20000)

    # 清理在途 + 创建完整演示任务（真实图 + 研判 + 批准 + 两轮）
    for it in api("/api/analyzes?limit=8").get("items", []):
        if it.get("status") in ("executing", "awaiting_confirmation", "approved", "replanning"):
            try:
                api(f"/api/tasks/{it['analysis_id']}/approval", {"action": "terminate", "reason": "截图前清理"})
            except Exception:
                pass

    page.get_by_role("button", name="火情监测", exact=True).first.click()
    page.locator(".fm-tools-drawer[open]").wait_for(timeout=10000)
    page.locator("input[type=file]").first.set_input_files("e2e/real/AoF07718.jpg")
    page.get_by_text("影像已接入").wait_for(timeout=10000)
    page.get_by_role("button", name="开始研判").click()
    page.get_by_text("任务状态 · 待确认").wait_for(timeout=240000)
    page.wait_for_timeout(1200)
    d = api("/api/analyzes?limit=1")
    aid = d["items"][0]["analysis_id"]
    print("演示任务:", aid, flush=True)

    boxes: dict = {}

    # ── 1. 火情监测 · 研判后（顶部）──
    ann1 = [
        (1, ".fm-stage", None, "影像主舞台（真实火场照片 + YOLO 检测框）"),
        (2, ".ev-toggle", None, "原图 / 检测结果 切换"),
        (3, "[aria-label='火情识别结果']", None, "火情识别结果（视觉观察陈述）"),
        (4, ".model-badges", None, "YOLO / VLM / GLM 三模型状态徽章"),
        (5, "[aria-label='火情量化']", None, "火情量化（等级 / FLP，规则引擎计算）"),
        (6, ".environment-panel", None, "环境影响（坡度 / 植被 / 风速 / 温湿度）"),
        (7, ".fm-action-bar", None, "指挥操作条（吸底常驻）"),
    ]
    shot(page, "command_assess", boxes, ann1)

    # 抽屉展开态（收起→展开）
    page.evaluate("() => { const m = document.querySelector('main'); if (m) m.scrollTop = 99999; }")
    page.wait_for_timeout(300)
    drawer = page.locator(".fm-tools-drawer summary")
    if drawer.count():
        drawer.click()
        page.wait_for_timeout(600)
    ann1b = [
        (1, ".dropzone", None, "拖拽区：拖入 / 选择火场照片"),
        (2, ".vlm-toggle", None, "勾选「上传时调用 VLM 解释」"),
        (3, ".model-status", None, "模型状态行（YOLO / VLM / GLM 在线情况）"),
        (4, ".demo-scripts", None, "演示脚本（一键主场景）"),
    ]
    shot(page, "command_drawer", boxes, ann1b, to_top=False)

    # ── 2. 批准 + 两轮推演 ──
    page.get_by_role("button", name="机群调度").first.click()
    page.locator(".plan-summary").wait_for(timeout=20000)
    page.wait_for_timeout(800)
    page.get_by_role("button", name="批准主方案").first.click()
    page.wait_for_function("document.querySelector('.task-badge')?.textContent?.includes('执行中')", timeout=30000)
    page.wait_for_timeout(2500)
    try:
        page.locator(".round-list").wait_for(timeout=60000)
    except Exception:
        pass
    for _ in range(2):
        try:
            page.locator("button", has_text="执行下一轮监测").first.click(timeout=4000)
            page.wait_for_timeout(3000)
        except Exception:
            break

    # ── 3. 机群调度（顶部）──
    ann3 = [
        (1, ".dispatch-map-col", None, "调度地图（火点 / 水源 / 航线）"),
        (2, ".dispatch-alert-card", None, "火情告警卡（等级 / 面积 / 风向）"),
        (3, ".dp-hero", None, "调度结论（可控 / 维持 / 失控三态）"),
        (4, ".dp-metrics", None, "五指标盒（预计时间 / 出动架次 / 版本 / 约束 / 缺口）"),
        (5, ".plan-summary", None, "方案摘要（中文重规划触发原因）"),
        (6, ".dp-approval", None, "方案审批表单"),
        (7, ".approval-actions .primary", None, "批准主方案"),
        (8, ".squadron-tables", None, "2+6+4 编组表"),
    ]
    shot(page, "dispatch_top", boxes, ann3)

    page.evaluate("() => { const m = document.querySelector('main'); if (m) m.scrollTop = m.scrollHeight; }")
    page.wait_for_timeout(400)
    ann3b = [
        (1, ".round-list", None, "推演账本（每轮 FLP 账目）"),
        (2, ".replay-panel", None, "回放面板"),
    ]
    shot(page, "dispatch_ledger", boxes, ann3b, to_top=False)

    # ── 4. 态势总览 ──
    page.get_by_role("button", name="态势总览").first.click()
    page.locator(".map-toolbar").wait_for(timeout=15000)
    page.wait_for_timeout(2000)
    ann4 = [
        (1, ".map-toolbar-heading", None, "页面标题与推演轮次提示"),
        (2, ".view-toggle", None, "平面 / 三维地形切换"),
        (3, ".map-legend", None, "六个图层开关"),
        (4, ".map-toolbar-tools .legend-item", 2, "指定火点 / 语音广播"),
        (5, ".fire-zone-ring", None, "火区范围环（脉冲动画）"),
        (6, ".map-side-rail", None, "右侧信息栏（实时画面 / 任务执行 / 环境）"),
        (7, ".map-statusbar", None, "底部方案条（当前方案 / 结论 / 下次评估）"),
    ]
    shot(page, "map", boxes, ann4)

    # ── 5. 数据分析 ──
    page.get_by_role("button", name="数据分析").first.click()
    page.locator(".ana-stats").first.wait_for(timeout=15000)
    page.wait_for_timeout(1800)
    ann5 = [
        (1, ".ana-stats", None, "当前任务复盘 KPI（FLP 变化 / 压制效率）"),
        (2, ".ana-charts", None, "过火面积趋势 + 火情量化 FLP 曲线"),
        (3, ".ana-kpis", None, "资源消耗 KPI（W20 / 架次 / 补水 / 换电）"),
        (4, ".ana-rounds-scroll", None, "前后轮次对比表"),
        (5, ".ana-pick", None, "多任务对比勾选"),
    ]
    shot(page, "analysis_top", boxes, ann5)
    page.evaluate("() => { const m = document.querySelector('main'); if (m) m.scrollTop = m.scrollHeight; }")
    page.wait_for_timeout(400)
    ann5b = [
        (1, ".replay-panel", None, "复盘回放（逐轮回放）"),
        (2, ".report-output", None, "报告输出（在线 / 图文 / JSON / PDF）"),
    ]
    shot(page, "analysis_bottom", boxes, ann5b, to_top=False)

    # ── 6. 资源管理 ──
    page.get_by_role("button", name="资源管理").first.click()
    page.locator(".drone-card").first.wait_for(timeout=15000)
    page.wait_for_timeout(1000)
    ann6 = [
        (1, ".res-kpis", None, "资源 KPI 一行（总数 / 可用 / 库存）"),
        (2, ".drone-card", 0, "机卡（SOC / 健康 / 载荷 / 任务）"),
        (3, ".dc-tele", 0, "遥测展开按钮"),
        (4, ".fleet-bottom-grid", None, "库存与水源候选表"),
    ]
    shot(page, "fleet_top", boxes, ann6)
    page.evaluate("() => { const m = document.querySelector('main'); if (m) m.scrollTop = m.scrollHeight; }")
    page.wait_for_timeout(400)
    shot(page, "fleet_bottom", boxes, [], to_top=False)

    # ── 7. 任务管理 ──
    page.get_by_role("button", name="任务管理").first.click()
    page.locator(".arc-row").first.wait_for(timeout=15000)
    page.wait_for_timeout(800)
    ann7 = [
        (1, ".arc-filters", None, "状态过滤器（全部 / 进行中 / 已完成 / 已终止）"),
        (2, ".arc-row", 0, "任务归档行（点行恢复任务）"),
        (3, ".cmp-pick", 0, "勾选 2-4 个任务横向对比"),
        (4, ".hr-detail", 0, "详情按钮（任务全流程）"),
    ]
    shot(page, "history", boxes, ann7)

    with open(os.path.join(os.path.dirname(OUT), "boxes.json"), "w", encoding="utf-8") as fh:
        json.dump(boxes, fh, ensure_ascii=False, indent=1)
    print("boxes.json 完成", flush=True)
    browser.close()
    pw.stop()


if __name__ == "__main__":
    main()
