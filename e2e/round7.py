"""第 7 轮：多帧图片序列上传（UI 多选 → 序列提示 → 序列研判成功）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import Session, report  # noqa: E402


def main() -> int:
    session = Session()
    ok = True
    detail = ""
    base = Path(__file__).resolve().parent
    try:
        session.goto_app()
        session.page.get_by_text("系统运行正常").wait_for(timeout=15000)

        # 多选：fire2.jpg（序列帧）+ fire.jpg（主文件/最新一帧）
        session.page.set_input_files("input[type=file]", [str(base / "fire2.jpg"), str(base / "fire.jpg")])
        session.page.wait_for_function(
            "document.querySelector('.dropzone strong')?.textContent?.includes('序列 2 帧')", timeout=10000
        )
        ok &= report(7, "序列帧计数提示", True)

        # 序列研判成功（默认火 1800m² 不可控，plan-summary 显示序列 FLP）
        session.page.get_by_role("button", name="启动智能研判").click()
        session.page.wait_for_function(
            "document.querySelector('.plan-summary')?.textContent?.includes('FLP：')", timeout=150000
        )
        ok &= report(7, "序列研判完成", True)

        # 后端真实收到序列：最新任务 result.visual_sequence.frame_count == 2
        sequence_ok = session.page.evaluate(
            "() => fetch('/api/analyzes').then(r=>r.json()).then(d=>{"
            "const t=d.items[0];return t.result?.visual_sequence?.frame_count})"
        )
        ok &= report(7, "后端序列 visual_sequence", sequence_ok == 2, f"frame_count={sequence_ok}")

        session.assert_clean_console("round7")
        ok &= report(7, "控制台无错误", True)
        session.screenshot("round7_multiframe")
    except Exception as error:
        ok = False
        detail = str(error)[:200]
        try:
            detail += " | badge=" + session.page.locator(".task-badge").inner_text()
            notice = session.page.locator(".notice")
            if notice.count():
                detail += " | notice=" + notice.inner_text()[:120]
        except Exception:
            pass
        session.screenshot("round7_failure")
    finally:
        session.cleanup_task()
        session.close(ok)
    if not ok:
        print("detail:", detail)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
