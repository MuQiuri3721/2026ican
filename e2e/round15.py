"""第 15 轮：指挥员问答专项——GLM 在线时为真回答（无离线前缀、接地任务数据）；
未配 Key 时为离线确定性降级。模式自适应（按 /api/llm-status 实际状态断言）。"""
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import BACKEND, Session, report  # noqa: E402


def main() -> int:
    session = Session()
    ok = True
    detail = ""
    page = session.page
    try:
        session.goto_app()

        with urllib.request.urlopen(BACKEND + "/api/llm-status", timeout=10) as resp:
            online = json.loads(resp.read().decode()).get("mode") == "glm"

        # 演训模拟建案（无影像路径，最快拿到可问答的任务）
        page.get_by_role("button", name="生成随机火情").click()
        page.locator(".scenario-facts").wait_for(timeout=8000)
        page.get_by_role("button", name="开始模拟").click()
        page.locator(".plan-summary").wait_for(timeout=150000)

        # 问答面板模式标签与 /api/llm-status 一致
        tag = page.locator(".chat-panel .llm-tag")
        tag.wait_for(timeout=8000)
        expect = "GLM 已接入" if online else "离线规则模式"
        ok &= report(15, f"问答面板模式标签({expect})", expect in tag.inner_text(), tag.inner_text())

        # 首问：回答模式正确
        page.locator(".chat-input-row input").fill("现在火势控制住了吗？为什么出动这些无人机？")
        page.locator(".chat-send").click()
        # 等真实回答（排除"思考中…"占位气泡，它同样带 agent 类）
        page.wait_for_selector(".chat-bubble.agent:not(.typing)", timeout=60000)
        answer = page.locator(".chat-bubble.agent:not(.typing)").last.inner_text()
        if online:
            ok &= report(15, "GLM 真回答（无离线前缀）", "（离线规则模式）" not in answer,
                         answer[:110].replace("\n", " "))
            ok &= report(15, "回答接地任务数据", ("FLP" in answer or "级" in answer), answer[:70].replace("\n", " "))
        else:
            ok &= report(15, "离线确定性回答", "（离线规则模式）" in answer, answer[:110].replace("\n", " "))

        # 追问：历史保留、多轮可用
        page.locator(".chat-input-row input").fill("水剂还剩多少？")
        page.locator(".chat-send").click()
        page.wait_for_function("document.querySelectorAll('.chat-bubble.agent:not(.typing)').length >= 2", timeout=60000)
        bubbles = page.locator(".chat-bubble").count()
        ok &= report(15, "多轮问答历史", bubbles >= 4, f"bubbles={bubbles}")
        second = page.locator(".chat-bubble.agent:not(.typing)").last.inner_text()
        ok &= report(15, "回答接地库存数据", any(ch.isdigit() for ch in second), second[:90])

        session.assert_clean_console("round15")
        ok &= report(15, "控制台无错误", True)
        session.screenshot("round15_chat")
    except Exception as error:
        ok = False
        detail = f"{type(error).__name__}: {str(error)[:260]}"
        session.screenshot("round15_failure")
    finally:
        session.cleanup_task()
        session.close(ok)
    if not ok:
        print("detail:", detail)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
