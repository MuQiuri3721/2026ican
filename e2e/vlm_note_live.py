"""VLM 接入端到端验证：上传影像（勾选 VLM）→ 研判 → .vlm-note 渲染 VLM 解释块。

配合 e2e/mock_vlm_adapter.py（FIRE_VLM_ENDPOINT 一级来源）或真实 Key（二级直连）使用；
断言只依赖 vlm-analysis-v1 契约字段，两种真实来源均适用。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import Session, report  # noqa: E402

FIRE_IMAGE = str(Path(__file__).resolve().parent / "fire.jpg")


def main() -> int:
    session = Session()
    ok = True
    detail = ""
    try:
        session.goto_app()
        session.page.get_by_text("系统运行正常").wait_for(timeout=15000)

        session.page.set_input_files("input[type=file]", FIRE_IMAGE)
        session.page.get_by_text("影像已接入").wait_for(timeout=10000)
        # 勾选「上传时调用 VLM 解释」
        session.page.locator(".vlm-toggle input[type=checkbox]").check()
        ok &= report(2, "VLM 开关勾选", True)

        session.page.get_by_role("button", name="启动智能研判").click()
        note = session.page.locator(".vlm-note")
        note.wait_for(timeout=180000)  # 冷启动后端环境抓取可达 60-90s，60s 会误报超时
        head = note.locator(".vlm-note-head").inner_text()
        ok &= report(2, "VLM 解释块出现", "VLM 视觉解释" in head, head)

        body_text = note.locator("p").first.inner_text()
        ok &= report(2, "VLM 摘要渲染", len(body_text) > 8, body_text[:50])

        src = note.locator(".src-note").inner_text()
        real_source = ("vlm-adapter" in src) or ("vlm-glm" in src)
        ok &= report(2, "来源徽标=真实 VLM 来源", real_source, src)

        facts = note.locator(".vlm-note-facts span")
        facts_count = facts.count()
        facts_text = " | ".join(facts.nth(i).inner_text() for i in range(min(facts_count, 6)))
        ok &= report(2, "事实行(展平字段)", facts_count >= 2, facts_text)

        session.assert_clean_console("vlm_live")
        ok &= report(2, "控制台无错误", True)
        session.screenshot("vlm_note_live")
    except AssertionError as error:
        ok = False
        detail = str(error)[:300]
        session.screenshot("vlm_live_failure")
    finally:
        session.cleanup_task()
        session.close(ok)
    if not ok:
        print("detail:", detail)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
