"""Playwright E2E 测试基座：浏览器会话、控制台错误捕获、常用等待。

规范（Playwright skill）：role 选择器优先；禁用 waitForTimeout，统一 waitFor* / expect 轮询。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

from playwright.sync_api import sync_playwright, Page, BrowserContext

# E2E 前端目标可切换：默认 dev 5173；设 E2E_FRONTEND=http://localhost:4173 跑生产
# preview（交付形态，且规避 vite dev 代理长跑后对带 body POST 的间歇性楔死）
FRONTEND = os.environ.get("E2E_FRONTEND", "http://localhost:5173")
BACKEND = "http://127.0.0.1:8000"

_CHROMIUM = os.path.join(
    os.environ.get("LOCALAPPDATA", ""), "ms-playwright", "chromium-1234", "chrome-win64", "chrome.exe"
)

IGNORE_CONSOLE = (
    "favicon.ico",
    "fonts.googleapis.com",
    "fonts.gstatic.com",
)


class Session:
    def __init__(self, headless: bool = True):
        self._pw = sync_playwright().start()
        launch_options = {"headless": headless}
        if os.path.exists(_CHROMIUM):
            launch_options["executable_path"] = _CHROMIUM
        self.browser = self._pw.chromium.launch(**launch_options)
        self.context: BrowserContext = self.browser.new_context(viewport={"width": 1600, "height": 1000})
        self.page: Page = self.context.new_page()
        self.console_errors: list[str] = []
        self.page_errors: list[str] = []
        self.bad_responses: list[str] = []
        self.page.on("console", self._on_console)
        self.page.on("pageerror", self._on_pageerror)
        self.page.on("response", self._on_response)

    def _on_response(self, response) -> None:
        if response.status >= 400:
            # 终止任务时在途轮次被后端拒绝（409）属预期竞态，不算错误
            if response.status == 409 and response.url.rstrip("/").endswith("/rounds"):
                return
            self.bad_responses.append(f"{response.status} {response.url}")

    def _on_console(self, msg) -> None:
        if msg.type == "error":
            text = msg.text
            if not any(token in text for token in IGNORE_CONSOLE):
                self.console_errors.append(text)

    def _on_pageerror(self, error) -> None:
        self.page_errors.append(str(error))

    def goto_app(self) -> None:
        self.page.goto(FRONTEND)
        self.page.get_by_role("heading", name="森林火灾智能应急指挥平台").wait_for(timeout=30000)
        # 在线态守卫：前端启动探测 /api/health 一旦瞬时失败即降级"本地演示"且不再自愈
        # （vite dev 代理长跑后楔死时必现，round2-5 曾批量挂）。落地若见离线态则重载一次，
        # 重载后仍离线再放行（让脚本以真实失败呈现，不掩盖产品问题）。
        if self.page.get_by_text("本地演示模式").count():
            # networkidle 在新前端（数据分析页持续轮询）下永远达不到——load 即可，
            # 就绪判定交给下一行的标题等待
            self.page.reload(wait_until="load")
            self.page.get_by_role("heading", name="森林火灾智能应急指挥平台").wait_for(timeout=30000)
        self.page.get_by_text("系统运行正常").wait_for(timeout=20000)
        # 默认落地页是态势总览（大屏）；绝大多数轮次的上传/研判流程在火情监测页——统一导航
        if self.page.locator(".upload-panel").count() == 0:
            self.page.get_by_role("button", name="火情监测", exact=True).first.click()
            self.page.locator(".upload-panel").wait_for(timeout=8000)

    def api(self, method: str, path: str, payload: dict | None = None) -> dict:
        request = urllib.request.Request(
            BACKEND + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())

    def cleanup_task(self) -> None:
        """轮次自清理：终止本会话创建的任务并释放资源锁，避免跨轮 409。"""
        try:
            task_id = self.page.evaluate(
                "() => fetch('/api/analyzes').then(r=>r.json()).then(d=>{"
                "const t=d.items.find(x=>x.status==='executing'||x.status==='awaiting_confirmation');"
                "return t?t.analysis_id:''})"
            )
            if task_id:
                self.api("POST", f"/api/tasks/{task_id}/approval",
                         {"action": "terminate", "reason": "e2e cleanup"})
        except Exception:
            pass

    def errors(self) -> list[str]:
        # "Failed to load resource" 文本不含 URL，真实接口失败由 bad_responses 精确兜底
        return self.page_errors + [e for e in self.console_errors if "Failed to load resource" not in e]

    def assert_clean_console(self, context: str) -> None:
        problems = self.errors()
        real_bad = [u for u in self.bad_responses if "favicon" not in u]
        assert not problems and not real_bad, f"{context}: 浏览器错误 {problems[:3] or real_bad[:3]}"

    def screenshot(self, name: str) -> None:
        self.page.screenshot(path=f"e2e/artifacts/{name}.png", full_page=True)

    def close(self, passed: bool, cleanup: bool = True) -> None:
        # 默认收尾终止本会话任务并释放资源锁，避免跨轮 409
        if cleanup:
            try:
                self.cleanup_task()
            except Exception:
                pass
        self.context.close()
        self.browser.close()
        self._pw.stop()


def report(round_no: int, name: str, passed: bool, detail: str = "") -> bool:
    status = "PASS" if passed else "FAIL"
    print(f"[round {round_no}] {name}: {status}" + (f" | {detail}" if detail else ""))
    return passed
