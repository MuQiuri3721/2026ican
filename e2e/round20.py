"""第 20 轮：大屏投影模式（FE-60）——切换/持久化/键盘快捷键/字体放大。"""
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

        # 初始为普通模式：html 无 projection 类
        initial = page.evaluate("document.documentElement.classList.contains('projection')")
        ok &= report(20, "初始普通模式", initial is False, f"projection={initial}")

        # 点击投影按钮：html.projection 类 + localStorage 持久化
        page.locator("header .icon-btn").first.click()
        page.wait_for_function("document.documentElement.classList.contains('projection')", timeout=5000)
        stored = page.evaluate("localStorage.getItem('fireops-projection')")
        ok &= report(20, "投影开启并持久化", stored == "1", f"localStorage={stored}")

        # 刷新后仍保持投影（localStorage 恢复路径）
        page.reload()
        page.get_by_text("系统运行正常").wait_for(timeout=20000)
        ok &= report(20, "刷新后保持投影", page.evaluate("document.documentElement.classList.contains('projection')"))
        # 投影样式真实生效（强断言，FE-60 曾只挂类无样式，投影是空操作）：
        # hero 结论条仅在有研判结果后渲染（FE-82 后默认落地大屏无此元素）——改用对比断言：
        # 顶栏标题 16px→18px（html.projection 规则），投影开/关实测字号差 >0 即样式层真实生效
        def _h1_px():
            return page.evaluate(
                "parseFloat(getComputedStyle(document.querySelector('.topbar-title h1')).fontSize)"
            )
        px_on = _h1_px()
        page.keyboard.press("p")
        page.wait_for_function("!document.documentElement.classList.contains('projection')", timeout=5000)
        px_off = _h1_px()
        page.keyboard.press("P")
        page.wait_for_function("document.documentElement.classList.contains('projection')", timeout=5000)
        ok &= report(20, "投影字号放大", px_on > px_off, f"projection={px_on}px / normal={px_off}px")

        # P 键快捷键关闭 + 再次开启（键盘路径）
        page.keyboard.press("p")
        page.wait_for_function("!document.documentElement.classList.contains('projection')", timeout=5000)
        page.keyboard.press("P")
        page.wait_for_function("document.documentElement.classList.contains('projection')", timeout=5000)
        ok &= report(20, "P 键切换", True)

        # 收尾：退出投影模式（不留状态给其他轮次）
        page.locator("header .icon-btn").first.click()
        page.wait_for_function("!document.documentElement.classList.contains('projection')", timeout=5000)
        page.evaluate("localStorage.setItem('fireops-projection','0')")
        ok &= report(20, "退出投影还原", page.evaluate("localStorage.getItem('fireops-projection')") == "0")

        session.assert_clean_console("round20")
        ok &= report(20, "控制台无错误", True)
        session.screenshot("round20_projection")
    except Exception as error:
        ok = False
        detail = f"{type(error).__name__}: {str(error)[:260]}"
        session.screenshot("round20_failure")
    finally:
        session.cleanup_task()
        session.close(ok)
    if not ok:
        print("detail:", detail)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
