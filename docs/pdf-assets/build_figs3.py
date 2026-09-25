# -*- coding: utf-8 -*-
"""图3-3 / 图3-4 / 图3-6 生成器：HTML/SVG → playwright 截图。
配色规范（任务书统一）：环境蓝 #1b5fa8 · 火情橙红 #d62828/#e76f51 ·
无人机绿 #2f9e44 · 方案金 #b8860b · 反馈紫 #7b2cbf · 文字深灰 #3d4c5c。
从项目根运行：python docs/pdf-assets/build_figs3.py
"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "docs" / "pdf-assets"

BASE_CSS = """
* { margin:0; padding:0; box-sizing:border-box; font-family:"Microsoft YaHei","SimHei",sans-serif; }
body { background:#fff; color:#3d4c5c; }
.card { background:#f7fafc; border:1.5px solid #b9cbd8; border-radius:10px; padding:10px 12px; text-align:center; }
.card b { display:block; font-size:19px; color:#22384c; }
.card span { font-size:13px; color:#5c7186; }
.arrow-r { position:absolute; height:3px; background:#8aa2b5; }
.arrow-r::after { content:""; position:absolute; right:-1px; top:-5px; border-left:11px solid #8aa2b5; border-top:6.5px solid transparent; border-bottom:6.5px solid transparent; }
.tag { display:inline-block; font-size:13px; padding:2px 10px; border-radius:10px; }
"""

def shot(html_path, png_path, w, h):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(viewport={"width": w, "height": h}, device_scale_factor=2)
        pg.goto(html_path.as_uri())
        pg.wait_for_timeout(400)
        pg.screenshot(path=str(png_path))
        b.close()
    print("rendered", png_path.name)


# ================= 图3-3 多源环境与资源态势融合机制 =================
inputs33 = [
    ("地形", "SRTM 30米 高程/坡度/坡向", "#1b5fa8"),
    ("气象", "风速/风向/温湿度/降水", "#1b5fa8"),
    ("植被", "WorldCover 土地覆盖", "#1b5fa8"),
    ("水体与取水", "OSM 水体 · 候选水源", "#2a9d8f"),
    ("道路", "OSM 路网与通行性", "#2a9d8f"),
    ("火情感知", "航拍影像 · YOLO/VLM", "#d62828"),
    ("机群状态", "12 架 UAV · SOC/载荷", "#2f9e44"),
    ("库存与约束", "W20/C6/电池 · 用户要求", "#b8860b"),
]
pipe33 = [
    ("坐标关联", "报警点为入口<br>半径检索 5 千米"),
    ("单位统一", "米/度/升/千克/%<br>字段口径对齐"),
    ("来源标注", "source · mode<br>采集时间 · 坐标系"),
    ("环境快照", "snapshot_id = envsnap-哈希<br>不可变 · 随方案版本绑定"),
    ("黑板共享", "六角色读取同一份<br>结构化任务上下文"),
]
outs33 = ["火情状态", "环境状态", "人员状态", "资源状态", "任务约束"]

cards_l = "".join(
    f'<div class="card" style="border-color:{c};margin-bottom:12px;"><b style="color:{c};">{t}</b><span>{s}</span></div>'
    for (t, s, c) in inputs33
)
pipe_html = ""
py = 46
for i, (t, s) in enumerate(pipe33):
    pipe_html += f'''
    <div style="position:absolute;left:20px;top:{py}px;width:250px;" class="card">
      <b style="font-size:18px;">{i+1} {t}</b><span>{s}</span>
    </div>'''
    if i < 4:
        pipe_html += f'''<div style="position:absolute;left:138px;top:{py+92}px;width:3px;height:26px;background:#8aa2b5;"></div>'''
    py += 118
outs_html = "".join(
    f'<div class="card" style="width:250px;margin-bottom:11px;border-color:#1b5fa8;"><b style="font-size:17px;color:#1b5fa8;">{o}</b></div>'
    for o in outs33
)
html33 = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>{BASE_CSS}
.wrap {{ position:relative; width:1680px; height:1490px; padding:26px 30px; }}
.col-t {{ font-size:20px; font-weight:700; color:#22384c; margin-bottom:14px; text-align:center; }}
.col-t small {{ font-weight:400; font-size:13px; color:#5c7186; }}
</style></head><body><div class="wrap">
  <div style="position:absolute;left:60px;top:24px;width:340px;">
    <div class="col-t">多源输入<small>蓝/青=环境 · 红=火情 · 绿=机群 · 金=约束</small></div>{cards_l}
  </div>
  <div style="position:absolute;left:520px;top:24px;width:300px;">
    <div class="col-t">统一化处理管线<small>协同层五步</small></div>{pipe_html}
  </div>
  <div style="position:absolute;left:960px;top:24px;width:300px;">
    <div class="col-t">统一任务态势<small>五类状态输出</small></div>{outs_html}
    <div class="card" style="width:250px;border-color:#b8860b;border-width:2px;background:#fdf8ec;">
      <b style="color:#b8860b;">进入控制层</b><span>预测火势 · 生成调度方案</span>
    </div>
  </div>
  <div style="position:absolute;left:1330px;top:24px;width:320px;height:600px;background:#f2f7fb;border:1.5px dashed #b9cbd8;border-radius:12px;padding:16px;font-size:14.5px;color:#3d4c5c;line-height:1.9;">
    <b style="font-size:17px;color:#22384c;">来源标注契约</b><br>
    每项数据同时保留<br>
    <b>source</b>（来源服务）<br>
    <b>mode</b>（在线 / 离线）<br>
    <b>采集时间</b>（含 stale 标注）<br>
    <b>坐标系</b>（EPSG:32650 / 4326）<br>
    <b>状态</b>（verified 等）<br><br>
    环境刷新产生新观测并生成<b>新快照</b>；<br>
    新方案引用新快照，历史方案<br>保留原决策依据，全程可追溯。
  </div>
  <div style="position:absolute;left:30px;top:706px;width:1620px;">
    <div class="col-t" style="text-align:left;">地形证据 · 南京 SRTM 30 米离线交付成果<small>　高程 / 坡度 / 坡向三联 · 红框为紫金山示范林区任务点（32.0688°N, 118.8432°E）· 坡度→K_slope · 植被→K_fuel · 风速→K_wind · 水体→取水候选</small></div>
    <img src="fig3-3-srtm-zh.png" style="width:1620px;border:1px solid #d7e0e8;border-radius:8px;">
  </div>
</div></body></html>"""

p33 = ASSETS / "fig3-3.html"
p33.write_text(html33, encoding="utf-8")
shot(p33, ASSETS / "fig3-3.png", 1680, 1490)

# ================= 图3-4 火势预测与多约束调度决策机制 =================
inp4 = ["统一态势", "人员状态", "机群资源", "药剂库存", "用户约束"]
cons_ok = ["SOC ≥ 35% 出动", "返航 SOC ≥ 25%", "W20↔植被 · C6↔电气", "航程/速度可行", "健康度 ≥ 60", "库存足额扣减"]
cons_bad = ["SOC 不足淘汰", "药剂不匹配淘汰", "故障/信号弱淘汰", "超出动上限淘汰"]
html4 = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>{BASE_CSS}
.wrap {{ position:relative; width:1680px; height:1240px; padding:24px 30px; }}
.layer {{ position:absolute; border-radius:12px; padding:12px 16px; }}
.lt {{ font-size:19px; font-weight:700; }}
.chip {{ display:inline-block; border-radius:9px; padding:6px 13px; font-size:15px; margin:4px 3px; }}
</style></head><body><div class="wrap">
  <div class="layer" style="left:30px;top:20px;width:1620px;background:#f2f7fb;border:1.5px solid #1b5fa8;">
    <div class="lt" style="color:#1b5fa8;">输入 · 统一任务态势（来自协同层）</div>
    {''.join(f'<span class="chip" style="background:#fff;border:1.5px solid #1b5fa8;color:#1b5fa8;">{x}</span>' for x in inp4)}
  </div>

  <div class="layer" style="left:30px;top:130px;width:1040px;height:300px;background:#fff7f2;border:2px solid #d62828;">
    <div class="lt" style="color:#d62828;">预测层 · 火势负荷与发展（统一分钟推进）</div>
    <div style="background:#fff;border-radius:9px;padding:12px 16px;margin:10px 0;font-size:20px;text-align:center;">
      单格负荷 <b>B<sub>i</sub> = 10 × I<sub>i</sub> × K<sub>fuel</sub> × K<sub>wind</sub> × K<sub>slope</sub></b>
      <span style="font-size:14px;color:#5c7186;">（火焰强度 × 植被 × 风速 × 坡度，100m² 网格）</span>
    </div>
    <div style="background:#fff;border-radius:9px;padding:12px 16px;margin:10px 0;font-size:20px;text-align:center;">
      分钟推进 <b>FLP<sub>t+1</sub> = FLP<sub>t</sub> × (1 + g/60) − S<sub>t</sub></b>
      <span style="font-size:14px;color:#5c7186;">（自然增长 − 有效压制，1 分钟步长）</span>
    </div>
    <div style="font-size:15px;color:#5c7186;">输出：当前火情负荷 · 发展趋势（增长/压制/净变化）· 重点处置方向 · 控制时间区间</div>
  </div>
  <div class="layer" style="left:1100px;top:130px;width:550px;height:300px;background:#f2fbf4;border:2px solid #2f9e44;">
    <div class="lt" style="color:#2f9e44;">约束层 · 硬约束校验</div>
    {''.join(f'<div style="font-size:15.5px;margin:5px 0;color:#2f9e44;">✓ {x}</div>' for x in cons_ok)}
    {''.join(f'<div style="font-size:15.5px;margin:5px 0;color:#d62828;">✗ {x}</div>' for x in cons_bad)}
  </div>

  <div class="layer" style="left:30px;top:460px;width:1620px;background:#f4f6f9;border:1.5px solid #8aa2b5;">
    <div class="lt" style="color:#3d4c5c;">优化层 · 候选枚举 → 硬过滤 → 评分比较</div>
    <div style="display:flex;align-items:center;gap:14px;margin-top:8px;">
      <div class="card" style="flex:1;"><b>组合枚举</b><span>满足出动上限内<br>全部无人机组合</span></div>
      <div style="font-size:26px;color:#8aa2b5;">→</div>
      <div class="card" style="flex:1;"><b>完整航次校验</b><span>出发/作业/返航/补给<br>全程 SOC 预算</span></div>
      <div style="font-size:26px;color:#8aa2b5;">→</div>
      <div class="card" style="flex:1;"><b>统一分钟仿真</b><span>120 分钟处置过程<br>逐分钟预测</span></div>
      <div style="font-size:26px;color:#8aa2b5;">→</div>
      <div class="card" style="flex:1.4;border-color:#b8860b;"><b>评分 J</b><span>J = 0.40·时间 + 0.30·负荷<br>+ 0.15·能耗 + 0.10·物资 + 0.05·变化</span></div>
    </div>
  </div>

  <div class="layer" style="left:30px;top:650px;width:1620px;background:#fdf8ec;border:2px solid #b8860b;">
    <div class="lt" style="color:#b8860b;">输出层 · 三态结论与方案</div>
    <div style="display:flex;gap:14px;margin-top:8px;">
      <div class="card" style="flex:1;border-color:#2f9e44;"><b style="color:#2f9e44;">可控制</b><span>输出时间区间</span></div>
      <div class="card" style="flex:1;border-color:#e76f51;"><b style="color:#e76f51;">维持压制</b><span>时限内未完成</span></div>
      <div class="card" style="flex:1;border-color:#d62828;"><b style="color:#d62828;">不可控制</b><span>资源不足 · 请求增援</span></div>
      <div class="card" style="flex:1;border-color:#d62828;border-style:dashed;"><b style="color:#d62828;">资源缺口</b><span>缺什么 · 缺多少</span></div>
      <div class="card" style="flex:1.2;"><b>推荐 + 备选方案</b><span>机群/药剂/航线/补给</span></div>
    </div>
  </div>

  <div style="position:absolute;left:30px;top:768px;width:700px;border-top:3px dashed #8aa2b5;"></div>
  <div style="position:absolute;left:742px;top:754px;font-size:13px;color:#5c7186;">生成 ▼</div>
  <div style="position:absolute;left:950px;top:768px;width:700px;border-top:3px dashed #8aa2b5;"></div>
  <div style="position:absolute;left:800px;top:798px;width:0;height:0;border-left:44px solid transparent;border-right:44px solid transparent;border-bottom:76px solid #b8860b;"></div>
  <div style="position:absolute;left:800px;top:822px;width:88px;text-align:center;color:#fff;font-size:15px;font-weight:700;">用户<br>确认</div>
  <div style="position:absolute;left:843px;top:878px;width:3px;height:44px;background:#2f9e44;"></div>
  <div style="position:absolute;left:836px;top:920px;border-left:11px solid #2f9e44;border-top:6.5px solid transparent;border-bottom:6.5px solid transparent;"></div>
  <div style="position:absolute;left:866px;top:888px;font-size:17px;color:#2f9e44;font-weight:700;">批准后锁定资源 → 进入执行层</div>
  <div style="position:absolute;left:30px;top:800px;width:700px;font-size:15px;color:#5c7186;line-height:1.7;">
    拒绝 / 调整 → 回到候选生成，原因必填留痕；<br>方案进入 awaiting_confirmation 状态等待确认。
  </div>

  <div style="position:absolute;left:30px;top:1080px;width:1620px;background:#22384c;border-radius:10px;padding:14px 20px;text-align:center;">
    <span style="color:#e9c46a;font-size:19px;font-weight:700;">规则引擎计算全部安全关键数字（FLP · SOC · 药剂 · 数量 · 时间）</span>
    <span style="color:#cdd9e4;font-size:17px;">　多智能体负责组织工具调用、分工解释与建议</span>
  </div>
</div></body></html>"""

p34 = ASSETS / "fig3-4.html"
p34.write_text(html4, encoding="utf-8")
shot(p34, ASSETS / "fig3-4.png", 1680, 1010)

# ================= 图3-6 感知执行反馈重规划闭环 =================
# 真实轮账本（2026-09-24 任务 analysis-9df5149d8840 · 8 轮 × 5 分钟，来自 /api/tasks/{id}/rounds）
REAL = [
    {"r": 1, "before": 810.00, "growth": 28.55, "supp": 28.08, "net": 0.47, "after": 810.47},
    {"r": 2, "before": 810.47, "growth": 28.30, "supp": 18.72, "net": 9.58, "after": 820.05},
    {"r": 3, "before": 820.05, "growth": 29.11, "supp": 0.00, "net": 29.11, "after": 849.16},
    {"r": 4, "before": 849.16, "growth": 29.94, "supp": 28.08, "net": 1.86, "after": 851.02},
    {"r": 5, "before": 851.02, "growth": 29.74, "supp": 18.72, "net": 11.02, "after": 862.04},
    {"r": 6, "before": 862.04, "growth": 30.60, "supp": 0.00, "net": 30.60, "after": 892.64},
    {"r": 7, "before": 892.64, "growth": 31.49, "supp": 28.08, "net": 3.41, "after": 896.05},
    {"r": 8, "before": 896.05, "growth": 31.34, "supp": 18.72, "net": 12.62, "after": 908.67},
]
b_rounds = REAL
b_r0 = REAL[0]
ledger = {"before_flp": b_r0["before"], "growth_flp": b_r0["growth"], "suppression_flp": b_r0["supp"], "net_change_flp": b_r0["net"], "after_flp": b_r0["after"]}
ledger_cells = ""
for label, key, color in [
    ("before 起始", "before_flp", "#5c7186"),
    ("growth 增长", "growth_flp", "#e76f51"),
    ("suppression 压制", "suppression_flp", "#2f9e44"),
    ("net 净变化", "net_change_flp", "#1b5fa8"),
    ("after 结束", "after_flp", "#d62828"),
]:
    v = ledger.get(key)
    v = f"{v:.1f}" if isinstance(v, (int, float)) else "—"
    ledger_cells += f'<div class="lg-cell"><small>{label}</small><b style="color:{color};">{v}</b></div>'

# FLP 曲线（8 轮真实 after；橙点 = 补给间歇回升轮）
maxv = max(r["after"] for r in b_rounds) or 1
minv = min(r["after"] for r in b_rounds)
span = max(maxv - minv, 1)
pts, dots = "", ""
for i, r in enumerate(b_rounds):
    x = 66 + i * (556 / max(len(b_rounds) - 1, 1))
    y = 240 - (r["after"] - minv) / span * 190
    pts += f"{x:.0f},{y:.0f} "
    color = "#e76f51" if r["supp"] == 0 else "#1b5fa8"
    dots += f'<circle cx="{x:.0f}" cy="{y:.0f}" r="6" fill="{color}"/>'
    dots += f'<text x="{x:.0f}" y="{y - 12:.0f}" text-anchor="middle" font-size="13" fill="#5c7186">{r["after"]:.0f}</text>'

loop_nodes = [("执行", "#2f9e44"), ("状态更新", "#1b5fa8"), ("效果评估", "#e76f51"), ("重规划", "#7b2cbf"), ("新方案确认", "#b8860b")]
loop_html = ""
ly = 60
for i, (t, c) in enumerate(loop_nodes):
    loop_html += f'<div class="card" style="width:280px;border:2px solid {c};margin:0 0 0 40px;"><b style="color:{c};">{i+1} {t}</b></div>'
    if i < 4:
        loop_html += '<div style="margin:6px 0 6px 165px;font-size:22px;color:#7b2cbf;">↓</div>'
loop_html += '<div style="margin:2px 0 0 40px;font-size:14px;color:#7b2cbf;">↺ 评估后回到执行（紫虚线=反馈回路）</div>'

html6 = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>{BASE_CSS}
.wrap {{ position:relative; width:1680px; height:930px; padding:24px 30px; }}
.lg-cell {{ flex:1; background:#fff; border:1.5px solid #b9cbd8; border-radius:9px; text-align:center; padding:8px 4px; }}
.lg-cell small {{ display:block; font-size:13px; color:#5c7186; }}
.lg-cell b {{ font-size:22px; }}
.tl-node {{ text-align:center; width:150px; }}
.tl-node b {{ display:block; font-size:15px; color:#22384c; }}
.tl-node span {{ font-size:12.5px; color:#5c7186; }}
</style></head><body><div class="wrap">
  <div style="position:absolute;left:30px;top:20px;width:400px;">
    <div style="font-size:20px;font-weight:700;color:#22384c;margin-bottom:12px;">反馈复盘闭环</div>{loop_html}
  </div>
  <div style="position:absolute;left:520px;top:20px;width:660px;border:1.5px solid #b9cbd8;border-radius:12px;padding:10px;">
    <div style="font-size:18px;font-weight:700;color:#22384c;">逐轮 after FLP 曲线（真实任务 8 轮 × 5 分钟）</div>
    <svg width="640" height="270">
      <line x1="60" y1="255" x2="640" y2="255" stroke="#8aa2b5" stroke-width="2"/>
      <line x1="60" y1="20" x2="60" y2="255" stroke="#8aa2b5" stroke-width="2"/>
      <polyline points="{pts}" fill="none" stroke="#1b5fa8" stroke-width="3.5"/>
      {dots}
      <text x="14" y="34" font-size="13" fill="#5c7186">FLP</text>
    </svg>
    <div style="font-size:13.5px;color:#5c7186;"><span style="color:#1b5fa8;font-weight:700;">蓝点 = 有效压制轮</span> · <span style="color:#e76f51;font-weight:700;">橙点 = 补给间歇回升轮（suppression=0）</span> · 横轴 = 反馈轮次（5 分钟/轮）—— 账本如实反映间歇</div>
  </div>
  <div style="position:absolute;left:1210px;top:20px;width:440px;">
    <div style="font-size:18px;font-weight:700;color:#22384c;margin-bottom:10px;">单轮账本（第 {b_r0["r"]} 轮真实数据）</div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;">{ledger_cells}</div>
    <div style="font-size:13.5px;color:#5c7186;margin-top:10px;line-height:1.6;">before + growth − suppression = after<br>账本守恒由测试 test_P003 / test_T07 背书</div>
  </div>
  <div style="position:absolute;left:30px;top:620px;width:1620px;border-top:2px dashed #b9cbd8;"></div>
  <div style="position:absolute;left:30px;top:646px;font-size:19px;font-weight:700;color:#22384c;">一次任务的方案版本时间线（示例口径）</div>
  <div style="position:absolute;left:60px;top:806px;width:1540px;height:3px;background:#8aa2b5;"></div>
  <div style="position:absolute;left:60px;top:722px;display:flex;gap:96px;">
    {''.join(f'<div class="tl-node"><div style="width:17px;height:17px;border-radius:50%;background:{c};margin:0 auto 8px;"></div><b>{t}</b><span>{s}</span></div>' for (t, s, c) in [
        ("v1 方案确认", "用户批准 · 资源锁定", "#b8860b"),
        ("执行推演", "分钟推进 · 逐轮账本", "#2f9e44"),
        ("风变触发", "风速跨档 · 事件上报", "#7b2cbf"),
        ("v2 方案再确认", "新环境快照 · 再审批", "#b8860b"),
        ("任务完成", "FLP 压平 · 返航回收", "#2f9e44"),
        ("报告归档", "全生命周期证据", "#1b5fa8"),
    ])}
  </div>
  <div style="position:absolute;left:30px;top:846px;width:1620px;background:#f6f0fb;border:1.5px solid #7b2cbf;border-radius:10px;padding:12px 18px;font-size:16px;color:#3d4c5c;">
    <b style="color:#7b2cbf;">触发器：</b>负荷超基线 20% · 风速跨档 · 人员状态变化 · SOC 低于返航阈值 · 单机失能 · 信号下降 · 水源失效 · 连续 3 轮净涨
    —— <b>新方案 = 新环境快照 + 新资源状态 + 再审批</b>，关键事件可提前触发评估，不必机械等待完整轮次。
  </div>
</div></body></html>"""

p36 = ASSETS / "fig3-6.html"
p36.write_text(html6, encoding="utf-8")
shot(p36, ASSETS / "fig3-6.png", 1680, 930)
print("ALL FIGS DONE")
