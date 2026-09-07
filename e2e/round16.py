"""第 16 轮：视频经 UI 上传（自动抽帧→研判）+ 风变演练的"动作"轮次展示。

覆盖两个此前的 UI 盲区：
1. mp4 主文件经前端上传 → 平台抽帧 → visual_sequence → 研判完成；
2. 风变演练触发重规划后，轮次列表出现「动作 等待二次审批」（审计§九 next_action 展示）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import Session, report  # noqa: E402

VIDEO = str(Path(__file__).resolve().parent / "fire_growth.mp4")


def main() -> int:
    session = Session()
    ok = True
    detail = ""
    page = session.page
    try:
        session.goto_app()
        page.get_by_text("系统运行正常").wait_for(timeout=15000)

        # ---- ① 视频 UI 上传：抽帧 → 研判 ----
        page.set_input_files("input[type=file]", VIDEO)
        page.get_by_text("影像已接入").wait_for(timeout=15000)  # 单视频无「· 序列」后缀（那是多图提示）
        ok &= report(16, "视频接入", True)

        page.get_by_role("button", name="启动智能研判").click()
        page.locator(".plan-summary").wait_for(timeout=180000)
        ok &= report(16, "视频研判完成", True)

        aid = session.api("GET", "/api/analyzes?limit=1&slim=1")
        items = aid.get("items", aid) if isinstance(aid, dict) else aid
        tid = (items[0] or {}).get("analysis_id") or (items[0] or {}).get("id")
        envelope = session.api("GET", f"/api/analyze/{tid}")
        image_name = (envelope.get("input") or {}).get("image_name") or ""
        seq = ((envelope.get("result") or {}).get("visual_sequence") or {})
        ok &= report(16, "抽帧进入研判序列", image_name.endswith(".mp4") and seq.get("frame_count", 0) >= 2,
                     f"image={image_name} frames={seq.get('frame_count')}")

        # 清理视频任务
        if envelope.get("status") == "awaiting_confirmation":
            session.api("POST", f"/api/tasks/{tid}/approval", {"action": "terminate", "reason": "round16 清理"})

        # ---- ② 风变演练 → 动作 等待二次审批 ----
        page.get_by_role("button", name="清空并重新接入").click()
        page.get_by_role("button", name="指挥中枢").click()
        import re
        page.get_by_role("button", name="生成随机火情").click()
        page.locator(".scenario-facts").wait_for(timeout=8000)
        shifted = False
        for _ in range(25):
            facts = page.locator(".scenario-facts").inner_text()
            match = re.search(r"面积 (\d+) m²", facts)
            # 小火在风变轮之前就扑灭（round11 结论）：必须够大才能活到跨档轮
            if "风变演练" in facts and match and int(match.group(1)) >= 1500:
                shifted = True
                break
            page.get_by_role("button", name="重新生成火情").click()  # 上传面板按钮（重摇火情在地图任务栏）
            page.wait_for_timeout(600)
        ok &= report(16, "摇到风变演练场景(面积≥1500)", shifted,
                     page.locator(".scenario-facts").inner_text()[:100].replace("\n", " "))

        page.get_by_role("button", name="开始模拟").click()
        page.locator(".plan-summary").wait_for(timeout=150000)
        page.get_by_role("button", name="批准主方案").click()
        # 风变在第 2 轮注入 → 跨档触发重规划 → 回待确认 → 轮次列表动作提示
        page.wait_for_function(
            "document.querySelector('.round-list')?.textContent?.includes('等待二次审批')",
            timeout=180000,
        )
        rounds_text = page.locator(".round-list").inner_text()
        ok &= report(16, "轮次动作提示(等待二次审批)", "等待二次审批" in rounds_text,
                     rounds_text[:110].replace("\n", " "))

        session.assert_clean_console("round16")
        ok &= report(16, "控制台无错误", True)
        session.screenshot("round16")
    except AssertionError as error:
        ok = False
        detail = str(error)[:300]
        session.screenshot("round16_failure")
    finally:
        session.cleanup_task()
        session.close(ok)
    if not ok:
        print("detail:", detail)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
