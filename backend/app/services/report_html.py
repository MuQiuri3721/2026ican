"""独立 HTML 图文报告生成（FE-59，服务 E-3/P5 素材冻结）。

`build_report_html(item)` 把任务信封渲染为单文件 A4 报告（内联 CSS、零外部依赖，
浏览器打开即可「打印 → 另存为 PDF」）。所有插值经 html.escape，缺字段一律 "—"。
"""
import html
import json
from datetime import datetime


def _esc(value) -> str:
    return html.escape(str(value), quote=True)


def _fmt(value, suffix="") -> str:
    return "—" if value is None else f"{_esc(value)}{suffix}"


def _verdict(plan: dict) -> dict:
    verdict = plan.get("control_verdict") or ("can_control" if plan.get("can_control") else "cannot_control")
    reason = plan.get("control_reason_code") or ""
    if verdict == "can_control":
        return {"cls": "ok", "label": "可控制 · 处置方案成立"}
    if verdict == "maintain_only":
        detail = "时限内未完成" if reason == "time_limit_exceeded" else "慢压维持"
        return {"cls": "mid", "label": f"维持压制 · {detail}"}
    return {"cls": "bad", "label": "暂不可控 · 已输出资源缺口"}


def build_report_html(item) -> str:
    data = item.model_dump()
    task_id = data.get("analysis_id") or ""
    result = data.get("result") or {}
    fire = result.get("fire_assessment") or {}
    plan = result.get("dispatch_plan") or {}
    env = result.get("environment") or {}
    inventory = result.get("inventory") or {}
    rounds = data.get("rounds") or []
    events = data.get("events") or []
    verdict = _verdict(plan)
    window = plan.get("estimated_control_time") or {}
    window_text = f"{window['earliest_minutes']}–{window['latest_minutes']} 分钟" if window.get("earliest_minutes") is not None else "—（不可控输出缺口）"
    gaps = plan.get("resource_gap") or []
    gap_rows = "".join(
        f"<tr><td>{_fmt(g.get('resource'))}</td><td>{_fmt(g.get('required'))}</td>"
        f"<td>{_fmt(g.get('available'))}</td><td>{_fmt(g.get('gap'))}</td></tr>"
        for g in gaps if isinstance(g, dict))
    task_rows = "".join(
        f"<tr><td>{_esc(t.get('drone_id'))}</td><td>{_esc(t.get('task'))}</td>"
        f"<td>{_fmt(t.get('module'))}</td><td>{_fmt(t.get('target_flp'))}</td></tr>"
        for t in (plan.get("tasks") or []) if isinstance(t, dict))
    round_rows = ""
    for r in rounds:
        before = (r.get("before") or {}).get("fire_load_flp")
        after = (r.get("after") or {}).get("fire_load_flp")
        ledger = (r.get("after") or {}).get("flp_ledger") or {}
        ledger_text = (f"净 {ledger.get('net_change_flp')}（增长 {ledger.get('growth_flp')} · "
                       f"压制 {ledger.get('suppression_flp')}）") if ledger else "—"
        triggers = "、".join(r.get("replan_triggers") or r.get("replan_trigger") or []) or "无"
        round_rows += (f"<tr><td>{_fmt(r.get('round'))}</td><td>{_fmt(before)}</td><td>{_fmt(after)}</td>"
                       f"<td>{_esc(triggers)}</td><td>{_esc(ledger_text)}</td></tr>")
    event_rows = "".join(
        f"<tr><td>{_esc(str(e.get('timestamp') or '')[:19].replace('T', ' '))}</td>"
        f"<td>{_esc(e.get('stage'))}</td><td>{_esc(e.get('message'))}</td></tr>"
        for e in events[:80] if isinstance(e, dict))
    consumed = result.get("monitor", {}).get("resource_consumed") or {}
    provenance = result.get("execution_provenance") or {}
    input_data = data.get("input") or {}
    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>任务报告 · {_esc(task_id)}</title>
<style>
@page {{ size: A4; margin: 16mm }}
* {{ box-sizing: border-box }}
body {{ font-family: "Microsoft YaHei", "PingFang SC", system-ui, sans-serif; color: #1a2432; margin: 0; padding: 28px 34px; color-scheme: light }}
h1 {{ font-size: 24px; margin: 0 0 4px }}
h2 {{ font-size: 15px; margin: 26px 0 10px; padding-bottom: 6px; border-bottom: 2px solid #2563eb }}
.meta {{ color: #5f6b77; font-size: 12px; line-height: 1.8 }}
.banner {{ margin: 18px 0; padding: 14px 18px; border-radius: 8px; font-size: 18px; font-weight: 700 }}
.banner.ok {{ background: #e8f6f0; color: #0e8a5f; border: 1px solid #b9e2d0 }}
.banner.mid {{ background: #fdf6e9; color: #b45309; border: 1px solid #f0dfc0 }}
.banner.bad {{ background: #fdf0ea; color: #b84314; border: 1px solid #f3cdbc }}
table {{ width: 100%; border-collapse: collapse; font-size: 12.5px }}
th, td {{ border: 1px solid #dfe4e9; padding: 7px 10px; text-align: left; vertical-align: top }}
th {{ background: #f2f4f6; font-weight: 600 }}
.grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin: 14px 0 }}
.stat {{ background: #f6f8f9; border: 1px solid #dfe4e9; border-radius: 8px; padding: 10px 12px }}
.stat small {{ display: block; color: #5f6b77; font-size: 11px; margin-bottom: 4px }}
.stat b {{ font-size: 17px }}
.note {{ color: #5f6b77; font-size: 11.5px; line-height: 1.7 }}
.printbar {{ position: fixed; top: 12px; right: 14px }}
.printbar button {{ padding: 8px 16px; border: 1px solid #2563eb; background: #2563eb; color: #fff; border-radius: 6px; cursor: pointer; font-size: 13px }}
@media print {{ .printbar {{ display: none }} body {{ padding: 0 }} }}
</style></head><body>
<div class="printbar"><button onclick="window.print()">打印 / 另存为 PDF</button></div>
<h1>森林火灾无人机处置任务报告</h1>
<div class="meta">
任务 <b>{_esc(task_id)}</b> · 状态 {_fmt(data.get('status'))} · 创建 {_fmt((data.get('created_at') or '')[:19].replace('T', ' '))}<br>
输入影像 {_fmt(input_data.get('image_name'))} · 场景 {_fmt(input_data.get('scene_id'))} · 人员分支 {_fmt(input_data.get('people_status'))}<br>
后端版本 {_fmt((result.get('execution_provenance') or {}).get('backend_commit'))} · 机群 {_fmt((result.get('execution_provenance') or {}).get('fleet_count'))} 架 · 报告生成 {generated}
</div>
<div class="banner {verdict['cls']}">{_esc(verdict['label'])}</div>
<h2>火情研判</h2>
<div class="grid">
<div class="stat"><small>火情等级</small><b>{_fmt(fire.get('label'))}</b></div>
<div class="stat"><small>火情负荷</small><b>{_fmt(fire.get('fire_load_flp'))} FLP</b></div>
<div class="stat"><small>火情面积</small><b>{_fmt(fire.get('fire_area_m2'))} m²</b></div>
<div class="stat"><small>研判置信度</small><b>{_fmt(fire.get('confidence'))}</b></div>
<div class="stat"><small>风速 / 风向</small><b>{_fmt(env.get('wind_speed'))} m/s</b></div>
<div class="stat"><small>火点坐标</small><b>{_fmt(fire.get('fire_center') or (result.get('scene') or {}).get('fire_origin_gps'))}</b></div>
<div class="stat"><small>增长率</small><b>{_fmt(fire.get('growth_rate'))}/h</b></div>
<div class="stat"><small>时间区间</small><b>{_esc(window_text)}</b></div>
</div>
<h2>处置方案</h2>
<table>
<tr><th>出动名单</th><td>{_esc('、'.join(plan.get('selected_uavs') or []))}</td></tr>
<tr><th>灭火编组</th><td>{_esc('、'.join(plan.get('firefighting_uavs') or []))}</td></tr>
<tr><th>药剂</th><td>{_fmt(plan.get('material_module'))} · {_fmt(plan.get('material_amount'))}</td></tr>
<tr><th>三态裁决</th><td>{_fmt(plan.get('control_verdict'))} · can_control={_fmt(plan.get('can_control'))}</td></tr>
</table>
<h2>任务分配</h2>
<table><tr><th>机号</th><th>任务</th><th>模块</th><th>目标 FLP</th></tr>{task_rows or '<tr><td colspan=4>—</td></tr>'}</table>
<h2>资源缺口</h2>
<table><tr><th>资源</th><th>需要</th><th>可用</th><th>缺口</th></tr>{gap_rows or '<tr><td colspan=4>无</td></tr>'}</table>
<h2>轮次账本</h2>
<table><tr><th>轮次</th><th>before FLP</th><th>after FLP</th><th>触发原因</th><th>分钟账本</th></tr>{round_rows or '<tr><td colspan=5>—</td></tr>'}</table>
<h2>资源消耗</h2>
<table><tr><th>水</th><td>{_fmt(consumed.get('water_liters'))} L</td><th>CO₂</th><td>{_fmt(consumed.get('co2_kg'))} kg</td>
<th>期末库存水</th><td>{_fmt(inventory.get('water_liters'))} L</td><th>备用电池</th><td>{_fmt(inventory.get('battery_packs'))}</td></tr></table>
<h2>任务事件（最近 {min(len(events), 80)} 条）</h2>
<table><tr><th style="width:150px">时间</th><th style="width:110px">阶段</th><th>消息</th></tr>{event_rows or '<tr><td colspan=3>—</td></tr>'}</table>
<p class="note">数字来源 · FLP ← 火情负荷评估（规则引擎） · 时间区间 ← 统一分钟推进核心仿真 · 三态裁决 ← control_verdict · 缺口 ← 硬约束校验。本报告由系统自动生成（{_esc(generated)}），全部数值可在 dispatch_plan.json 中追溯。</p>
</body></html>"""
