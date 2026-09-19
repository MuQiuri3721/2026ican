"""第 21 轮：现场采集（阶段二）——stub 摄像头流 → 抓帧 → 自动进入完整研判链路。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import Session, report  # noqa: E402

CAMERA_STUB = """
navigator.mediaDevices.getUserMedia = async (constraints) => {
  const canvas = document.createElement('canvas');
  canvas.width = 640; canvas.height = 480;
  const ctx = canvas.getContext('2d');
  let hue = 20;
  setInterval(() => {
    hue = (hue + 15) % 360;
    ctx.fillStyle = `hsl(${hue}, 55%, 45%)`;
    ctx.fillRect(0, 0, 640, 480);
    ctx.fillStyle = '#ffdd55';
    ctx.beginPath(); ctx.arc(320, 240, 90, 0, Math.PI * 2); ctx.fill();
  }, 120);
  ctx.fillStyle = '#444'; ctx.fillRect(0, 0, 640, 480);
  return canvas.captureStream(10);
};
"""


def main() -> int:
    session = Session()
    ok = True
    detail = ""
    page = session.page
    try:
        page.add_init_script(CAMERA_STUB)
        session.goto_app()
        page.get_by_text("系统运行正常").wait_for(timeout=20000)

        # 打开相机取景
        page.get_by_role("button", name="现场采集").click()
        page.locator(".camera-pane video").wait_for(timeout=10000)
        ok &= report(21, "相机取景打开", True)

        # 抓帧并研判：自动接图 + 自动启动分析
        page.get_by_role("button", name="抓帧并研判").click()
        page.get_by_text("影像已接入").wait_for(timeout=10000)
        ok &= report(21, "抓帧自动接入", True)
        file_label = page.evaluate("document.querySelector('.dropzone span')?.textContent || ''")
        ok &= report(21, "采集文件名标记", "现场采集" in file_label, file_label[:60])
        # 取景窗应自动关闭
        ok &= report(21, "取景窗自动关闭", page.locator(".camera-pane").count() == 0)

        # 自动进入研判（无需再点启动按钮）
        page.locator(".plan-summary").wait_for(timeout=300000)
        badge = page.locator(".task-badge").inner_text()
        ok &= report(21, "采集后自动研判", "待确认" in badge, badge)

        session.assert_clean_console("round21")
        ok &= report(21, "控制台无错误", True)
        session.screenshot("round21_capture")
    except Exception as error:
        ok = False
        detail = f"{type(error).__name__}: {str(error)[:260]}"
        session.screenshot("round21_failure")
    finally:
        session.cleanup_task()
        session.close(ok)
    if not ok:
        print("detail:", detail)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
