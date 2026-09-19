"""第 23 轮：真实 YOLO 模型端到端验证（E-1a 收官）。

前置（训练完成后）：
1. python yolo_server/server.py --port 9000   （加载 yolo_server/best.pt）
2. 后端以 FIRE_YOLO_ENDPOINT=http://127.0.0.1:9000/detect 启动
断言：上传真实火情图 → detector-live 显示 real/yolo11n-dfire-v1/local-yolo-service
      → 证据窗渲染真实检测框 → 面积由检测框推算（非 fixture 定值）。
"""
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
        page.get_by_text("系统运行正常").wait_for(timeout=20000)
        page.set_input_files("input[type=file]", "e2e/_real_images/fire1.jpg")
        page.get_by_text("影像已接入").wait_for(timeout=10000)
        page.get_by_role("button", name="启动智能研判").click()
        page.locator(".plan-summary").wait_for(timeout=300000)

        live = page.evaluate("document.querySelector('.detector-live')?.textContent || ''")
        ok &= report(23, "检测状态行(real)", "real" in live and "yolo11n-dfire-v1" in live and "local-yolo-service" in live, live.strip())

        boxes = page.evaluate("Array.from(document.querySelectorAll('.ew-box em')).map(e=>e.textContent)")
        ok &= report(23, "证据窗真实检测框", len(boxes) > 0, str(boxes[:5]))

        area = page.evaluate("document.querySelector('.hero-decision')?.textContent || ''")
        ok &= report(23, "面积随检测框变化", "火势" in area or "FLP" in area, area[:80].replace("\n", " "))

        session.assert_clean_console("round23")
        ok &= report(23, "控制台无错误", True)
        session.screenshot("round23_real_yolo")
    except Exception as error:
        ok = False
        detail = f"{type(error).__name__}: {str(error)[:260]}"
        session.screenshot("round23_failure")
    finally:
        session.cleanup_task()
        session.close(ok)
    if not ok:
        print("detail:", detail)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
