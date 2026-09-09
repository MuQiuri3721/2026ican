# -*- coding: utf-8 -*-
"""UI 布局审计截图：全页签（含研判后状态与地图页）。"""
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import Session  # noqa: E402

OUT = Path("artifacts/ui_audit")
OUT.mkdir(parents=True, exist_ok=True)


def api(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request("http://127.0.0.1:8000" + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    return json.load(urllib.request.urlopen(req, timeout=120))


def main():
    # 造一个研判完成任务（不调 VLM，offline，秒级），供"研判后"状态截图
    aid = None
    try:
        env = api("POST", "/api/analyze", {"scene_id": "forest-demo-01", "use_vlm": False,
                                           "environment_mode": "offline", "image_name": "small"})
        aid = env["analysis_id"]
        print("任务就绪:", aid)
    except Exception as e:
        print("造任务失败(继续截初始态):", str(e)[:80])

    session = Session()
    try:
        session.goto_app()
        session.page.get_by_text("系统运行正常").wait_for(timeout=15000)
        session.page.wait_for_timeout(1200)
        session.page.screenshot(path=str(OUT / "1-command-initial.png"), full_page=True)

        # 恢复研判态任务
        if aid:
            try:
                session.page.get_by_role("button", name="任务日志").count()
                hist = session.page.get_by_text("历史任务")
                if hist.count():
                    hist.first.click()
                    session.page.wait_for_timeout(600)
                    row = session.page.locator(f"text={aid}")
                    if row.count():
                        row.first.click()
                        session.page.wait_for_timeout(1500)
            except Exception as e:
                print("恢复任务失败:", str(e)[:80])

        session.page.get_by_role("button", name="指挥中枢").click()
        session.page.wait_for_timeout(1200)
        session.page.screenshot(path=str(OUT / "2-command-analyzed.png"), full_page=True)

        session.page.get_by_role("button", name="无人机集群").click()
        session.page.wait_for_timeout(1200)
        session.page.screenshot(path=str(OUT / "3-fleet.png"), full_page=True)

        session.page.get_by_role("button", name="林区态势").click()
        session.page.wait_for_timeout(4500)
        session.page.screenshot(path=str(OUT / "4-map.png"), full_page=True)

        session.page.get_by_role("button", name="任务日志").click()
        session.page.wait_for_timeout(1000)
        session.page.screenshot(path=str(OUT / "5-logs.png"), full_page=True)

        # 协作页签（tab pills）
        agents_tab = session.page.get_by_role("tab", name="Agent 协作")
        if agents_tab.count():
            agents_tab.click()
            session.page.wait_for_timeout(900)
            session.page.screenshot(path=str(OUT / "6-agents.png"), full_page=True)

        # 视图 tab pills（任务概览/实时监测）
        ov = session.page.get_by_role("tab", name="任务概览")
        if ov.count():
            ov.click()
            session.page.wait_for_timeout(900)
            session.page.screenshot(path=str(OUT / "7-overview.png"), full_page=True)

        print("截图完成 →", OUT)
    finally:
        if aid:
            try:
                api("POST", f"/api/tasks/{aid}/approval", {"action": "terminate", "reason": "审计清场"})
            except Exception:
                pass
        session.cleanup_task()
        session.close(True)


if __name__ == "__main__":
    main()
