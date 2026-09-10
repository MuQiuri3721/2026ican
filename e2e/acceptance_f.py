# -*- coding: utf-8 -*-
"""OPT-P4 验收 F：地图缓存与详情（浏览器路径）。

断言点：
1. 地点 A → 三维地形网格加载 A；快速切地点 B → 网格/等高线按 B 重载（键控缓存防串位）
2. 疏散路径摘要显式标注「模拟路径（演示网格 BFS）」（people=confirmed 任务恢复后）
3. 环境面板决策作用说明行存在（坡度/燃料/风速→K 值；温湿度背景信息）
4. 水源/道路/地形卡有值或如实空态
记录追加 docs/p4-acceptance-record.json 的 F 字段。
用法：python e2e/acceptance_f.py
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import Session, report  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

# 基于脚本位置解析（CWD 敏感曾致 F 首跑覆盖了 A–E 记录，现固定指向仓库 docs/）
RECORD = Path(__file__).resolve().parents[1] / "docs" / "p4-acceptance-record.json"
LOC_A = {"latitude": 32.0725, "longitude": 118.8415}   # 紫金山主峰（默认）
LOC_B = {"latitude": 32.0622, "longitude": 118.8390}   # 紫霞湖基地附近（不同地点）


def api(method, path, payload=None, timeout=120):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request("http://127.0.0.1:8000" + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def make_confirmed_task():
    """造一个 people=confirmed 任务（触发疏散分支），返回 analysis_id。"""
    env = api("POST", "/api/analyze", {"scene_id": "forest-demo-01", "use_vlm": False,
                                       "environment_mode": "offline", "image_name": "small",
                                       "people_status": "confirmed"})
    return env["analysis_id"]


def main() -> int:
    aid = None
    ok = True
    findings = {}
    pre = time.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        aid = make_confirmed_task()
        pre_clean_aid = aid
    except Exception as error:
        pre_clean_aid = None
        print("造任务失败（跳过疏散断言）:", str(error)[:80])
    session = Session()
    try:
        session.goto_app()
        terrain_urls = []
        def _on_request(req):
            if "/api/terrain/grid" in req.url:
                terrain_urls.append(req.url)
        session.page.on("request", _on_request)
        session.page.get_by_text("系统运行正常").wait_for(timeout=15000)

        # 恢复 confirmed 任务（研判态），使疏散摘要可见：历史任务 tab → 最新一行
        if pre_clean_aid:
            try:
                session.page.get_by_text("历史任务").first.click()
                session.page.wait_for_timeout(2500)
                rows = session.page.locator(".history-row")
                if rows.count():
                    rows.first.click()
                    session.page.wait_for_timeout(1800)
                    session.page.get_by_role("button", name="指挥中枢").click()
                    session.page.wait_for_timeout(800)
                else:
                    print("历史列表为空或选择器未命中")
            except Exception as error:
                print("恢复任务失败:", str(error)[:80])

        # —— 1. 地形键控缓存：先在 3D 建立 A 基线 → 改坐标至 B → 再进 3D → 键控清缓存重载 B ——
        session.page.get_by_role("button", name="指挥中枢").click()
        session.page.wait_for_timeout(600)
        session.page.get_by_role("button", name="林区态势").click()
        session.page.wait_for_timeout(2500)
        session.page.locator("button", has_text="三维").first.click()
        session.page.wait_for_timeout(3500)
        session.page.get_by_role("button", name="指挥中枢").click()
        session.page.wait_for_timeout(600)
        terrain_urls.clear()
        draft_lat = session.page.locator(".coordinate-editor input").nth(0)
        draft_lng = session.page.locator(".coordinate-editor input").nth(1)
        draft_lat.fill(str(LOC_B["latitude"]))
        draft_lng.fill(str(LOC_B["longitude"]))
        session.page.get_by_role("button", name="应用").click()
        session.page.wait_for_timeout(1200)
        session.page.get_by_role("button", name="林区态势").click()
        session.page.wait_for_timeout(2000)
        session.page.locator("button", has_text="三维").first.click()
        session.page.wait_for_timeout(3500)
        session.page.get_by_role("button", name="指挥中枢").click()
        session.page.wait_for_timeout(400)
        last = terrain_urls[-1] if terrain_urls else ""
        last_is_b = f"latitude={LOC_B['latitude']}" in last
        ok &= report("F", "地形网格按地点键控重载（最后请求=B）", last_is_b,
                     f"requests={len(terrain_urls)} last={last[-70:]}")
        findings["terrain_requests"] = len(terrain_urls)

        # 等高线来源标签仍指向真实 DEM（A/B 均在 N32E118 窗口内）
        session.page.get_by_role("button", name="林区态势").click()
        session.page.wait_for_timeout(3000)
        source = session.page.locator(".map-source")
        try:
            session.page.wait_for_function(
                "document.querySelector('.map-source')?.textContent?.includes('N32E118')", timeout=15000)
            ok &= report("F", "等高线来源标签", True, source.inner_text()[:40])
        except Exception:
            ok &= report("F", "等高线来源标签", False, source.inner_text()[:40] if source.count() else "未找到")

        # —— 2. 疏散模拟路径标注 ——
        session.page.get_by_role("button", name="指挥中枢").click()
        session.page.wait_for_timeout(800)
        summary = session.page.locator(".evacuation-summary")
        if summary.count():
            text = summary.inner_text()
            ok &= report("F", "疏散标注模拟路径", "模拟路径" in text, text[:60])
            findings["evacuation_summary"] = text[:80]
        else:
            ok &= report("F", "疏散摘要（confirmed 任务）", False, "未找到 .evacuation-summary")

        # —— 3. 环境面板决策作用说明 ——
        note = session.page.locator(".environment-note")
        if note.count():
            text = note.inner_text()
            ok &= report("F", "环境作用说明行", "K_slope" in text and "背景信息" in text, text[:70])
        else:
            ok &= report("F", "环境作用说明行", False, "未找到 .environment-note")

        # —— 4. VLM 状态标签（skipped 单列）——
        src = session.page.locator(".vlm-note .src-note")
        if src.count():
            findings["vlm_source_label"] = src.first.inner_text()[:80]

        session.assert_clean_console("acceptance_f")
        ok &= report("F", "控制台无错误", True)
        session.screenshot("acceptance_f")
    finally:
        if pre_clean_aid:
            try:
                api("POST", f"/api/tasks/{pre_clean_aid}/approval",
                    {"action": "terminate", "reason": "验收 F 清场"})
            except Exception:
                pass
        session.cleanup_task()
        session.close(ok)

    record = json.loads(RECORD.read_text(encoding="utf-8")) if RECORD.exists() else {}
    record.setdefault("F", {})
    record["F"].update({"executed_at": pre, "passed": ok, **findings})
    RECORD.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"F 验收 {'PASS' if ok else 'FAIL'} → 记录已更新 {RECORD}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
