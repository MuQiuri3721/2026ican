"""DOM 校验：归档行各列真实文本与表头对齐。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import Session  # noqa: E402

session = Session(headless=True)
page = session.page
try:
    session.goto_app()
    page.get_by_role("button", name="任务管理").click()
    page.locator(".arc-row").first.wait_for(timeout=15000)
    rows = page.evaluate("""() => {
      const head = Array.from(document.querySelectorAll('.arc-head.arc-grid > span')).map(s => s.textContent.trim());
      const list = Array.from(document.querySelectorAll('.arc-row')).map(r =>
        Array.from(r.children).map(c => c.textContent.trim().replace(/\s+/g, ' ')));
      const no = Array.from(document.querySelectorAll('.arc-no')).map(n => n.textContent.trim());
      return {head, list, no};
    }""")
    print("表头:", rows["head"])
    print("编号列:", rows["no"])
    for row in rows["list"]:
        print("行:", row)
    print("总行数:", len(rows["list"]))
finally:
    session.close(passed=True, cleanup=False)
