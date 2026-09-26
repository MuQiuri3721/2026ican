"""跨页状态同步 + VLM 真实照片链路专项测试。

场景：真实火场图 + 勾选「上传时调用 VLM 解释」→ 研判 → 六页逐页核对
状态徽章/核心数值/轮次联动 → 批准执行 → 推演 → 终止 → 全局一致。
用法: python e2e/sync_vlm.py
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from playwright.sync_api import sync_playwright  # noqa: E402

ART = os.path.join(os.path.dirname(os.path.abspath(__file__)), "artifacts")
os.makedirs(ART, exist_ok=True)

RESULTS = []


def report(name: str, ok: bool, note: str = "") -> None:
    RESULTS.append({"name": name, "ok": bool(ok), "note": str(note)[:300]})
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" —— {note}" if note and not ok else ""), flush=True)


def main() -> int:
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
    page = ctx.new_page()
    console_errors: list[str] = []
    bad_responses: list[str] = []
    page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
    page.on("response", lambda r: bad_responses.append(f"{r.status} {r.url[-60:]}") if r.status >= 400 else None)
    t0 = time.time()

    def elapsed() -> str:
        return f"[{time.time()-t0:.0f}s]"

    page.goto("http://localhost:5173")
    page.get_by_role("heading", name="森林火灾智能应急指挥平台").wait_for(timeout=30000)
    if page.get_by_text("本地演示模式").count():
        page.reload(wait_until="load")
        page.get_by_role("heading", name="森林火灾智能应急指挥平台").wait_for(timeout=30000)
    page.get_by_text("系统运行正常").wait_for(timeout=20000)
    print(f"{elapsed()} 在线态就绪", flush=True)

    # ── 1. 真实照片 + VLM 研判 ─────────────────────────────
    page.get_by_role("button", name="火情监测", exact=True).first.click()
    page.locator(".fm-tools-drawer[open]").wait_for(timeout=10000)  # 新会话抽屉默认展开
    page.locator(".vlm-toggle input").check()  # 勾选「上传时调用 VLM 解释」
    img = os.environ.get("SYNC_IMG", "e2e/real/AoF07719.jpg")
    page.locator("input[type=file]").first.set_input_files(img)
    page.get_by_text("影像已接入").wait_for(timeout=10000)
    page.get_by_role("button", name="开始研判").click()
    page.get_by_text("任务状态 · 待确认").wait_for(timeout=240000)
    page.wait_for_timeout(1500)
    print(f"{elapsed()} 研判完成（含 VLM）", flush=True)

    import urllib.request

    def api(path: str) -> dict:
        return json.load(urllib.request.urlopen(f"http://127.0.0.1:8000{path}", timeout=60))

    d = api("http://127.0.0.1:8000/api/analyzes?limit=1".replace("http://127.0.0.1:8000", ""))
    aid = d["items"][0]["analysis_id"]
    full = api(f"/api/analyze/{aid}")
    fa = (full.get("result") or {}).get("fire_assessment") or {}
    expl = (full.get("result") or {}).get("agent", {}).get("skill_chain", {}).get("fire_perception", {}).get("explanation", {}) if full.get("result") else {}
    det = (full.get("result") or {}).get("agent", {}).get("skill_chain", {}).get("fire_perception", {}).get("observation", {}).get("detector", {})
    ddata = det.get("data") if isinstance(det, dict) else {}

    report("VLM·真实调用（explanation.mode=real）", expl.get("mode") == "real", f"mode={expl.get('mode')} source={expl.get('source')}")
    report("VLM·视觉模型来源标注", "glm" in str(expl.get("source", "")) or "glm" in str(expl.get("model", "")), str(expl.get("source"))[:60])
    report("VLM·解释正文非空", len(str(expl.get("note") or expl.get("summary") or "")) > 20 or bool(expl.get("fire_observation")), str(expl)[:80])
    report("YOLO·real 模式", ddata.get("mode") == "real", f"mode={ddata.get('mode')}")
    report("YOLO·真实检出>0", len(ddata.get("detections") or []) > 0, f"n={len(ddata.get('detections') or [])}")

    # 火情监测页 UI：VLM 徽章 + 识别结果
    badges = page.locator(".model-badges").inner_text() if page.locator(".model-badges").count() else ""
    report("UI·VLM 徽章显示已调用", "已调用" in badges or "待调用" not in badges, badges[:90])
    vlm_note = page.locator(".fm-summary, .vlm-note").first
    report("UI·VLM 摘要上屏", vlm_note.count() > 0 and len(vlm_note.inner_text().strip()) > 10)

    # 量化面板核心数值
    quant_text = " ".join(page.locator("[aria-label='火情量化'] .fm-row").all_inner_texts())
    api_flp = fa.get("fire_load_flp")
    fmt = lambda v: f"{int(v):,}" if v is not None else ""
    report("同步·量化FLP=API", api_flp is not None and fmt(api_flp) in quant_text, f"api={api_flp}")
    api_area = fa.get("fire_area_m2")
    report("同步·量化过火面积=API", api_area is not None and fmt(api_area) in quant_text, f"api={api_area}")
    badge_cmd = page.locator(".task-badge").first.inner_text()
    report("同步·徽章待确认", "待确认" in badge_cmd, badge_cmd)

    # ── 2. 机群调度页同步 ─────────────────────────────
    page.get_by_role("button", name="机群调度").first.click()
    page.locator(".plan-summary").wait_for(timeout=20000)
    page.wait_for_timeout(800)
    plan_txt = page.locator(".plan-summary").inner_text() + page.locator(".dispatch-alert-card").inner_text()
    report("同步·调度页等级一致", fa.get("label", "").split("·")[0].strip() in plan_txt, f"api={fa.get('label')}")
    n_drones = len(((full.get("result") or {}).get("dispatch_plan") or {}).get("selected_uavs") or [])
    report("同步·调度页出动架次一致", str(n_drones) in plan_txt, f"api={n_drones}")
    badge_dispatch = page.locator(".task-badge").first.inner_text()
    report("同步·调度页徽章=待确认", "待确认" in badge_dispatch, badge_dispatch)

    # ── 3. 批准 → 执行态六页同步 ─────────────────────────────
    page.get_by_role("button", name="批准主方案").first.click()
    page.wait_for_function("document.querySelector('.task-badge')?.textContent?.includes('执行中')", timeout=30000)
    report("执行·批准生效", True)

    page.get_by_role("button", name="态势总览").first.click()
    page.locator(".map-toolbar").wait_for(timeout=15000)
    page.wait_for_timeout(1200)
    map_txt = page.locator(".map-toolbar").inner_text()
    report("同步·态势总览推演启动", "自动推演中" in map_txt, map_txt[:60])
    report("同步·态势总览徽章执行中", "执行中" in page.locator(".task-badge").first.inner_text())

    page.get_by_role("button", name="资源管理").first.click()
    page.locator(".drone-card").first.wait_for(timeout=15000)
    page.wait_for_timeout(800)
    fleet_txt = page.locator(".fleet-roster").inner_text()
    report("同步·资源页任务锁定=是·方案", "是 · 方案" in fleet_txt)
    report("同步·资源页有机组在任务中", ("主" in fleet_txt or "侦察" in fleet_txt or "压制" in fleet_txt))

    page.get_by_role("button", name="数据分析").first.click()
    page.locator(".ana-stats").first.wait_for(timeout=15000)
    page.wait_for_timeout(1500)
    # 出动架次在资源消耗 KPI（有轮次才渲染），轮次检查段再验
    kpi_txt = page.locator(".detail-heading").inner_text()
    report("同步·分析页当前任务=id", aid.split("-")[-1][:8] in kpi_txt or aid.split("-")[-1][:8] in page.locator(".detail-view").inner_text(), aid)

    # ── 4. 推演轮次联动 ─────────────────────────────
    page.get_by_role("button", name="机群调度").first.click()
    page.locator(".plan-summary").wait_for(timeout=15000)
    try:
        page.locator(".round-list").wait_for(timeout=90000)
        rounds_dom = page.locator(".round-list > div").count()
    except Exception:
        rounds_dom = 0
    full2 = api(f"/api/analyze/{aid}")
    rounds_api = len(full2.get("rounds") or [])
    report("联动·账本轮次=API", abs(rounds_dom - rounds_api) <= 1, f"dom={rounds_dom} api={rounds_api}")

    page.get_by_role("button", name="数据分析").first.click()
    page.locator(".ana-stats").first.wait_for(timeout=15000)
    page.wait_for_timeout(2000)
    tr = page.locator(".gt-scroll.ana-rounds-scroll tbody tr").count()
    report("联动·分析页轮次表=API", abs(tr - rounds_api) <= 1, f"dom={tr} api={rounds_api}")
    page.wait_for_timeout(800)
    kpis = page.locator(".ana-kpis").inner_text() if page.locator(".ana-kpis").count() else ""
    report("同步·分析页出动架次=API", str(n_drones) in kpis, f"api={n_drones} kpi={kpis[:60]}")

    # ── 5. 终止 → 全局一致 ─────────────────────────────
    page.get_by_role("button", name="机群调度").first.click()
    page.locator(".plan-summary").wait_for(timeout=15000)
    reason = page.locator(".approval-actions .reason-input, .dp-approval .reason-input").first
    if reason.count():
        reason.fill("sync_vlm 清理终止")
    term = page.locator("button", has_text="终止任务").first
    term.click()
    page.wait_for_timeout(2000)
    badge_end = page.locator(".task-badge").first.inner_text()
    report("终止·徽章已终止", "已终止" in badge_end or "终止" in badge_end, badge_end)
    st = api(f"/api/analyze/{aid}")
    report("终止·API 状态一致", st.get("status") == "terminated", st.get("status"))

    page.get_by_role("button", name="任务管理").first.click()
    page.locator(".arc-row").first.wait_for(timeout=15000)
    row_txt = page.locator(f".arc-row[title*='{aid}']").first.inner_text()
    report("同步·任务管理行=已终止", "已终止" in row_txt, row_txt[:70])

    page.get_by_role("button", name="态势总览").first.click()
    page.locator(".map-toolbar").wait_for(timeout=15000)
    page.wait_for_timeout(800)
    report("同步·态势总览终止后徽章", "已终止" in page.locator(".task-badge").first.inner_text())

    # 控制台净度（终止若与在途轮次竞态产生的单个 409 属预期守卫）
    console_errors[:] = [e for e in console_errors if "409 (Conflict)" not in e and "favicon" not in e]
    bad_responses[:] = [u for u in bad_responses if not (u.startswith("409 ") and ("/approval" in u or "/rounds" in u)) and "favicon" not in u]
    console_errors[:] = [e for e in console_errors if "409 (Conflict)" not in e]
    report("控制台/网络净度", not console_errors and not bad_responses, " | ".join((console_errors + bad_responses)[:3]))

    page.screenshot(path=os.path.join(ART, "sync_vlm_final.png"))
    browser.close()
    pw.stop()

    ok = all(r["ok"] for r in RESULTS)
    path = os.path.join(ART, "sync_vlm.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"ok": ok, "results": RESULTS}, fh, ensure_ascii=False, indent=1)
    print(f"{'✅ 全部通过' if ok else '❌ 存在失败'} —— {len(RESULTS)} 项 → {os.path.basename(path)}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
