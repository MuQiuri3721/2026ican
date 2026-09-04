"""出动推演动画手动验证（临时脚本）。"""
import sys
sys.path.insert(0, "e2e")
from harness import Session

POS_JS = "() => { const m = document.querySelector('.amap-marker[title*=\\'E1\\']'); return m ? m.style.transform : '' }"
BADGES_JS = "() => Array.from(document.querySelectorAll('.tmap-badge')).map(b => b.textContent).filter(Boolean)"

s = Session()
try:
    s.goto_app()
    s.page.set_input_files("input[type=file]", "e2e/small-fire.jpg")
    s.page.get_by_text("影像已接入").wait_for(timeout=10000)
    s.page.get_by_role("button", name="启动智能研判").click()
    s.page.locator(".plan-summary").wait_for(timeout=150000)
    s.page.get_by_role("button", name="批准主方案").click()
    s.page.wait_for_function("document.querySelector('.task-badge')?.textContent?.includes('执行中')", timeout=30000)
    s.page.locator(".sim-clock").wait_for(timeout=8000)
    print("mission 启动 ✓ |", s.page.locator(".sim-clock").inner_text())
    s.page.get_by_role("button", name="林区态势").click()
    s.page.locator(".tmap-fire").wait_for(timeout=20000)
    p1 = s.page.evaluate(POS_JS)
    s.page.wait_for_timeout(2500)
    p2 = s.page.evaluate(POS_JS)
    print("E1 位置随时间变化:", p1 != p2)
    s.page.wait_for_timeout(1500)
    print("相位徽章:", s.page.evaluate(BADGES_JS))
    s.page.wait_for_function("document.querySelectorAll('.round-list > div').length >= 2", timeout=40000)
    print("自动推演 2 轮 ✓ |", s.page.locator(".sim-clock").inner_text())
    print("monitorResult:", s.page.locator(".monitor-result").inner_text()[:130])
    s.screenshot("mission_running")
    s.page.get_by_role("button", name="指挥中枢").click()
    s.page.get_by_placeholder("驳回/终止原因（必填）").fill("验证完成")
    s.page.get_by_role("button", name="终止任务").click()
    s.page.wait_for_function("document.querySelector('.task-badge')?.textContent?.includes('已终止')", timeout=30000)
    s.page.wait_for_timeout(600)
    print("终止后 sim-clock:", s.page.locator(".sim-clock").count())
    s.assert_clean_console("mission")
    print("CONSOLE CLEAN")
finally:
    s.close(True)
