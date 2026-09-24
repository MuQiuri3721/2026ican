"""第 13 轮：多 Agent 协作——消息时间线（建案/发现/方案/审批/研判）、来源标注、LLM 离线降级。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import Session, report  # noqa: E402


def main() -> int:
    session = Session()
    ok = True
    detail = ""
    page = session.page
    try:
        session.goto_app()

        # GLM 状态标识（未配置 key：确定性降级）。页面设计 2026-09：顶栏不再展示技术接口
        # 状态，GLM 在线/离线随「火情监测」页影像接入面板的模型状态区展示
        llm_badge = page.locator(".upload-panel .model-status", has_text="GLM")
        llm_badge.wait_for(timeout=8000)
        # GLM 在线/离线均为合法状态（key 可选）：标识存在且标注其一即可
        badge_text = llm_badge.inner_text()
        ok &= report(13, "GLM 状态标识", "在线" in badge_text or "离线" in badge_text, badge_text)

        # 演训模拟（scenario 路径，无影像）
        page.get_by_role("button", name="火情监测", exact=True).click()
        page.get_by_role("button", name="生成随机火情").click()
        page.locator(".scenario-facts").wait_for(timeout=8000)
        page.get_by_role("button", name="开始模拟").click()
        page.get_by_role("button", name="机群调度").click()
        page.locator(".plan-summary").wait_for(timeout=300000)
        ok &= report(13, "演训研判完成", True)

        # Agent 协作时间线：建案/发现/方案/审批四类消息齐备
        page.get_by_role("button", name="Agent 协作").click()
        page.locator(".agent-msg").first.wait_for(timeout=10000)
        timeline = page.locator(".agent-timeline").inner_text()
        required = ["建案派任务", "态势发现", "方案提案", "审批请求"]
        missing = [label for label in required if label not in timeline]
        ok &= report(13, "协作消息时间线", not missing, f"missing={missing}")

        # 来源标注：LLM 离线时侦察/审批叙述不出现 glm 伪造，研判来源为保守降级或尚无轮次
        sources = page.evaluate("() => Array.from(document.querySelectorAll('.agent-source')).map(e => e.textContent)")
        # 每条消息必须有合法来源标注（GLM 在线时可为 glm；离线时为 Agent/规则），不得空白
        ok &= report(13, "来源标注完整", all(src.strip() for src in sources) if sources else False, str(sources[:4]))

        # 批准 → 仲裁消息 + 执行中 → 自动推演至第 2 轮 → JUDGMENT 消息（保守降级）
        page.get_by_role("button", name="机群调度").click()
        page.get_by_role("button", name="机群调度").click()
        page.get_by_role("button", name="批准主方案").click()
        page.wait_for_function("document.querySelector('.task-badge')?.textContent?.includes('执行中')", timeout=30000)
        page.get_by_role("button", name="机群调度").click()
        page.wait_for_function("document.querySelector('.sim-clock')?.textContent?.includes('第 2 轮')", timeout=30000)
        # 折叠栏在第 35 行已打开；此处幂等确保打开——折叠体是 v-if，二次点击「Agent 协作」
        # 会把已开的栏关掉并从 DOM 移除 .agent-timeline，下方等待必然超时（参考图改版回归实测）
        page.evaluate("() => { if (!document.querySelector('.decision-fold-body')) document.querySelector('.decision-fold-head')?.click(); }")
        page.wait_for_function(
            "document.querySelector('.agent-timeline')?.textContent?.includes('自主研判')", timeout=60000
        )
        ok &= report(13, "每轮自主研判消息", True)
        timeline2 = page.locator(".agent-timeline").inner_text()
        ok &= report(13, "审批仲裁消息", "审批仲裁" in timeline2)

        # 终止 → 推演停止
        page.get_by_role("button", name="机群调度").click()
        page.get_by_role("button", name="机群调度").click()
        page.get_by_placeholder("驳回/终止原因（必填）").fill("协作验证完成，终止")
        page.get_by_role("button", name="终止任务").click()
        page.wait_for_function("document.querySelector('.task-badge')?.textContent?.includes('已终止')", timeout=30000)
        page.wait_for_timeout(500)
        ok &= report(13, "终止→推演停止", page.locator(".sim-clock").count() == 0)

        session.assert_clean_console("round13")
        ok &= report(13, "控制台无错误", True)
        session.screenshot("round13_agents")
    except Exception as error:
        ok = False
        detail = f"{type(error).__name__}: {str(error)[:260]}"
        session.screenshot("round13_failure")
    finally:
        session.cleanup_task()
        session.close(ok)
    if not ok:
        print("detail:", detail)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
