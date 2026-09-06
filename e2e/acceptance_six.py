"""J-1 浏览器六场景验收（CONTRIBUTING §9）：自动化执行 + 截图留证。

每场景独立 Playwright 会话（自带任务清理），断言结果与截图归档 e2e/artifacts/j1/。
S3 的"风速升档重规划"在浏览器层以「按约束调整 → 新方案版本 + manual_adjust 触发」
覆盖（风速升档路径已由 tests/test_scenarios.py API 级覆盖）。
人工复核签字后方可关闭 J-1。
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import BACKEND, Session, report  # noqa: E402

J1_DIR = Path(__file__).resolve().parent / "artifacts" / "j1"
RESULTS = []


def record(scenario, name, passed, detail=""):
    RESULTS.append((scenario, name, passed, detail))
    print(f"[J1-{scenario}] {name}: {'PASS' if passed else 'FAIL'}" + (f" | {detail}" if detail else ""))
    return passed


def api(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BACKEND + path, data=data, headers={"Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def pre_clean_store():
    """开跑前清场：终止所有非终态任务并释放锁——演示后遗留的 executing 任务
    会让场景 1 的批准 409、推演钟永不出现（本次复跑实测踩中）。"""
    try:
        items = api("GET", "/api/analyzes?limit=100&slim=1")
        items = items if isinstance(items, list) else items.get("items", [])
        for t in items:
            if t.get("status") in {"executing", "approved", "replanning", "awaiting_confirmation"}:
                api("POST", f"/api/tasks/{t['analysis_id']}/approval", {"action": "terminate", "reason": "acceptance pre-clean"})
        print(f"[J1-pre] 清场完成，终止 {len([t for t in items if t.get('status') not in {'completed','terminated','failed'}])} 个遗留任务")
    except Exception as error:  # noqa: BLE001 —— 清场失败不阻断（后续场景自带清理）
        print(f"[J1-pre] 清场跳过：{error}")


def reroll_until_people(page, want, tries=12):
    """演训模拟的人员状态随机——重摇直到目标（在场/不在场/情况不明）。首次生成后按钮文案会变。
    两级坑：①"不在场"包含子串"在场"，裸子串匹配必错；②scenario-facts 渲染为
    「人员 不在场」（中间有空格），「人员{want}」整词同样匹配不上。用正则取值精确比对。"""
    import re
    generate = page.get_by_role("button", name="生成随机火情").or_(page.get_by_role("button", name="重新生成火情"))
    for _ in range(tries):
        generate.first.click()
        page.locator(".scenario-facts").wait_for(timeout=8000)
        facts = page.locator(".scenario-facts").inner_text()
        matched = re.search(r"人员\s*(在场|不在场|情况不明)", facts)
        if matched and matched.group(1) == want:
            return True
    return False


def scenario_1_absent_logistics():
    """场景 1：一般林地、无人——R 监测 + E 灭火 + S 物流。"""
    s = Session()
    ok = True
    try:
        page = s.page
        s.goto_app()
        page.get_by_role("button", name="指挥中枢").click()
        ok &= record(1, "随机到无人场景", reroll_until_people(page, "不在场"))
        page.get_by_role("button", name="开始模拟").click()
        page.locator(".plan-summary").wait_for(timeout=150000)
        chips = page.locator(".task-chips").inner_text()
        ok &= record(1, "S 单元物流任务", ("S1" in chips or "S2" in chips), chips[:80].replace("\n", " "))
        page.get_by_role("button", name="批准主方案").click()
        page.wait_for_function("document.querySelector('.sim-clock')?.textContent?.includes('第 1 轮')", timeout=45000)
        ok &= record(1, "批准→执行推演", True)
        time.sleep(2)
        s.screenshot(f"j1/S1_absent_logistics")
    finally:
        s.close(ok)
    return ok


def scenario_2_confirmed_guidance():
    """场景 2：确认有人——S 通信/指引 + 疏散路线，保留 E 保护疏散通道。"""
    s = Session()
    ok = True
    try:
        page = s.page
        s.goto_app()
        page.get_by_role("button", name="指挥中枢").click()
        ok &= record(2, "随机到有人场景", reroll_until_people(page, "在场"))
        page.get_by_role("button", name="开始模拟").click()
        page.locator(".plan-summary").wait_for(timeout=150000)
        summary = page.locator(".plan-summary").inner_text()
        ok &= record(2, "疏散路线生成", "疏散：" in summary, summary[:100].replace("\n", " "))
        page.get_by_role("button", name="批准主方案").click()
        page.wait_for_function("document.querySelector('.sim-clock')?.textContent?.includes('第 1 轮')", timeout=45000)
        page.get_by_role("button", name="林区态势").click()
        exit_marker = page.locator(".tmap-exit")
        exit_marker.wait_for(timeout=15000)
        ok &= record(2, "地图疏散出口标注", "疏散出口" in exit_marker.inner_text())
        time.sleep(1.5)
        s.screenshot("j1/S2_confirmed_guidance")
    finally:
        s.close(ok)
    return ok


def scenario_3_adjust_new_version():
    """场景 3：调整约束 → 重规划生成新方案版本（manual_adjust 触发）。"""
    s = Session()
    ok = True
    try:
        page = s.page
        s.goto_app()
        page.get_by_role("button", name="生成随机火情").click()
        page.get_by_role("button", name="开始模拟").click()
        page.locator(".plan-summary").wait_for(timeout=150000)
        page.locator(".people-risk select").nth(1).select_option("2")
        page.get_by_role("button", name="按约束调整").click()
        page.wait_for_function("document.querySelector('.plan-summary b')?.textContent?.includes('v2')", timeout=60000)
        summary = page.locator(".plan-summary").inner_text()
        ok &= record(3, "新方案版本 v2", "v2" in summary)
        ok &= record(3, "重规划触发标注", "manual_adjust" in summary, summary[:110].replace("\n", " "))
        time.sleep(0.5)
        s.screenshot("j1/S3_adjust_new_version")
    finally:
        s.close(ok)
    return ok


def scenario_4_soc_return_and_swap():
    """场景 4：SOC 不足——返航并启用换电/基地充电相位。"""
    s = Session()
    ok = True
    try:
        page = s.page
        s.goto_app()
        page.get_by_role("button", name="生成随机火情").click()
        page.get_by_role("button", name="开始模拟").click()
        page.locator(".plan-summary").wait_for(timeout=150000)
        page.get_by_role("button", name="批准主方案").click()
        page.wait_for_function("document.querySelector('.sim-clock')?.textContent?.includes('第 1 轮')", timeout=45000)
        page.get_by_role("button", name="林区态势").click()
        page.wait_for_function(
            "['返航中', '基地充电', '基地补水'].some(t => document.body.innerText.includes(t))", timeout=90000
        )
        ok &= record(4, "返航/换电相位出现", True)
        time.sleep(1.5)
        s.screenshot("j1/S4_soc_return_swap")
    finally:
        s.close(ok)
    return ok


def scenario_5_insufficient_gap():
    """场景 5：库存/能力不足——输出资源缺口，不承诺完成时间。"""
    s = Session()
    ok = True
    try:
        page = s.page
        s.goto_app()
        page.set_input_files("input[type=file]", str(Path(__file__).resolve().parent / "fire.jpg"))
        page.get_by_text("影像已接入").wait_for(timeout=10000)
        page.get_by_role("button", name="启动智能研判").click()
        page.locator(".plan-summary").wait_for(timeout=150000)
        summary = page.locator(".plan-summary").inner_text()
        ok &= record(5, "资源缺口展示", "缺口：" in summary and "无" not in summary.split("缺口：")[1][:6], summary[:110].replace("\n", " "))
        # BE-12b：压制增强后 fire.jpg 从「不可控」变为「可控但耗时很长（就地取水计入补给能力）」。
        # 断言改为契约语义一致性：缺口必须展示；时间窗与 can_control 严格互斥一致
        state = page.evaluate("""(async () => {
            const list = await (await fetch('/api/analyzes?limit=1&slim=1')).json();
            const tid = (Array.isArray(list) ? list : list.items)[0].analysis_id;
            const env = await (await fetch('/api/analyze/' + tid)).json();
            const dp = env.result.dispatch_plan || {};
            return { can: !!dp.can_control, win: (dp.estimated_control_time || {}).window_minutes || null,
                     gaps: (dp.resource_gap || []).map(g => g.resource) };
        })()""")
        has_window = bool(state["win"]) and len(state["win"]) == 2
        no_window_label = "时间区间：—" in summary
        ok &= record(5, "窗口与可控性一致", has_window == state["can"] and no_window_label == (not state["can"]),
                     f"can_control={state['can']} window={state['win']} gaps={state['gaps']}")
        time.sleep(0.5)
        s.screenshot("j1/S5_insufficient_gap")
    finally:
        s.close(ok)
    return ok


def scenario_6_reject_releases_locks():
    """场景 6：驳回方案——资源释放、状态正确。"""
    s = Session()
    ok = True
    try:
        page = s.page
        s.goto_app()
        page.get_by_role("button", name="生成随机火情").click()
        page.get_by_role("button", name="开始模拟").click()
        page.locator(".plan-summary").wait_for(timeout=150000)
        page.locator(".reason-input").fill("验收场景 6：驳回方案")
        page.get_by_role("button", name="驳回").click()
        # 系统语义：驳回 = 释放资源锁并回到「待确认」等待新方案（store.py approval CAS）
        page.wait_for_function("document.querySelector('.task-badge')?.textContent?.includes('待确认')", timeout=30000)
        ok &= record(6, "驳回→回到待确认", True)
        time.sleep(1)
        items = api("GET", "/api/analyzes")["items"]
        active = [i for i in items if i["status"] in ("executing", "approved", "replanning")]
        ok &= record(6, "资源锁释放（无在途任务）", not active, f"active={len(active)}")
        time.sleep(0.5)
        s.screenshot("j1/S6_reject_released")
    finally:
        s.close(ok)
    return ok


def main() -> int:
    J1_DIR.mkdir(parents=True, exist_ok=True)
    print("=== J-1 浏览器六场景验收（自动化执行 + 截图留证） ===")
    pre_clean_store()
    scenarios = [
        scenario_1_absent_logistics,
        scenario_2_confirmed_guidance,
        scenario_3_adjust_new_version,
        scenario_4_soc_return_and_swap,
        scenario_5_insufficient_gap,
        scenario_6_reject_releases_locks,
    ]
    # 单场景异常不中止整套：一处的偶发超时不应掩盖其余场景的验收结论
    outcomes = []
    for index, scenario in enumerate(scenarios, start=1):
        try:
            outcomes.append(scenario())
        except Exception as error:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            record(index, "场景执行异常", False, f"{type(error).__name__}: {str(error)[:160]}")
            outcomes.append(False)
    passed = sum(outcomes)
    print(f"=== J-1 汇总：{passed}/6 场景通过，截图归档 {J1_DIR} ===")
    (J1_DIR / "结果.md").write_text(
        "\n".join(f"- {'✅' if p else '❌'} S{k}：{n}" for k, (_s, n, p, _d) in zip(range(1, 7), RESULTS)),
        encoding="utf-8",
    )
    return 0 if all(outcomes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
