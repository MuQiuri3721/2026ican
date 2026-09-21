# -*- coding: utf-8 -*-
"""图5-2 生成器：读 curves.json（冻结场景 A/B/C 真实重跑数据）→ HTML/SVG → 截图。

从项目根运行：python docs/pdf-assets/build_fig5_2.py
"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
DATA = json.loads((ROOT / "e2e" / "artifacts" / "pdf-materials" / "curves.json").read_text(encoding="utf-8"))
A, B, C = DATA["cases"]

def natural(before, g):
    return before * (1 + g / 60) ** 5 if g is not None else before

# ---- 图1：正常小火（A）柱对 ----
a_rounds = A["rounds"]
a_bars = ""
for i, r in enumerate(a_rounds):
    x = 90 + i * 150
    maxv = max(r["before"], r["after"], natural(r["before"], r["growth_rate"])) or 1
    h = lambda v: v / 50 * 150  # y: 0..50 FLP -> 0..150px (倒置)
    a_bars += f'''
    <rect x="{x}" y="{170 - h(r["before"])}" width="44" height="{h(r["before"])}" rx="4" fill="#c9d9ea"/>
    <rect x="{x + 52}" y="{170 - h(r["after"])}" width="44" height="{max(h(r["after"]), 0)}" rx="4" fill="#1b5fa8"/>
    <text x="{x + 22}" y="{170 - h(r["before"]) - 8}" text-anchor="middle" font-size="14" fill="#5c7186">{r["before"]:.0f}</text>
    <text x="{x + 74}" y="{170 - h(r["after"]) - 8}" text-anchor="middle" font-size="14" font-weight="700" fill="#14497f">{r["after"]:.0f}</text>
    <text x="{x + 48}" y="192" text-anchor="middle" font-size="13" fill="#7a8b9c">第 {r["round"]} 轮</text>'''

# ---- 图2：补给间歇（B）折线 ----
b_rounds = B["rounds"]
W, H = 560, 168
xs = lambda i: 44 + i * (W - 60) / (len(b_rounds) - 1)
lo, hi = 140, 195
ys = lambda v: 18 + (hi - v) / (hi - lo) * (H - 46)
before_pts = " ".join(f"{xs(i):.1f},{ys(r['before']):.1f}" for i, r in enumerate(b_rounds))
after_pts = " ".join(f"{xs(i):.1f},{ys(r['after']):.1f}" for i, r in enumerate(b_rounds))
nat_pts = " ".join(f"{xs(i):.1f},{ys(natural(r['before'], r['growth_rate'])):.1f}" for i, r in enumerate(b_rounds))
marks = ""
strip = ""
for i, r in enumerate(b_rounds):
    x = xs(i)
    net = r["net"] or 0
    if net > 0:
        marks += f'<path d="M{x} {ys(r["after"]) - 12} l6 10 h-12 z" fill="#d96a2b"/>'
    ph = "w" if r["phases"].get("working") else ("s" if r["phases"].get("servicing") else "c")
    color = {"w": "#2f8f5b", "s": "#4a90d9", "c": "#d9a24a"}[ph]
    strip += f'<rect x="{x - 14:.1f}" y="{H - 22}" width="28" height="12" rx="2" fill="{color}"/>'
    marks += f'<text x="{x}" y="{H - 4}" text-anchor="middle" font-size="11" fill="#7a8b9c">{r["round"]}</text>'

html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; font-family:"Microsoft YaHei","PingFang SC",sans-serif; }}
  body {{ width:1680px; height:850px; background:#fff; position:relative; overflow:hidden; }}
  .stage {{ position:absolute; inset:24px; display:flex; gap:18px; }}
  .panel {{ background:#fbfcfe; border:1px solid #e2e9f0; border-radius:14px; padding:16px 18px; }}
  .p-title {{ font-size:19px; font-weight:700; color:#14497f; margin-bottom:4px; display:flex; align-items:center; gap:8px; }}
  .p-title i {{ width:9px; height:9px; border-radius:2px; background:#1b5fa8; }}
  .p-sub {{ font-size:12.5px; color:#8a99a8; margin-bottom:12px; }}
  /* 左：场景矩阵 */
  .scen {{ width:470px; }}
  .scen-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
  .scard {{ border:1px solid #dde6ee; border-radius:10px; padding:11px 13px; background:#fff; min-height:148px; }}
  .scard h4 {{ font-size:15.5px; color:#14497f; margin-bottom:7px; }}
  .scard h4 em {{ font-style:normal; font-size:11.5px; color:#fff; background:#1b5fa8; border-radius:4px; padding:1px 6px; margin-right:6px; }}
  .scard .row {{ font-size:12.5px; color:#5c7186; line-height:1.5; margin-bottom:4px; }}
  .scard .row b {{ color:#39536b; font-weight:600; }}
  /* 中：代表结果 */
  .mid {{ flex:1; display:flex; flex-direction:column; gap:14px; }}
  .chartbox {{ background:#fff; border:1px solid #dde6ee; border-radius:10px; padding:10px 14px 8px; }}
  .chartbox h5 {{ font-size:15px; color:#39536b; margin-bottom:2px; }}
  .chartbox .cap {{ font-size:12px; color:#8a99a8; margin-bottom:4px; }}
  .legend {{ font-size:12px; color:#5c7186; display:flex; gap:14px; margin-top:2px; }}
  .legend i {{ display:inline-block; width:18px; height:4px; border-radius:2px; margin-right:4px; vertical-align:middle; }}
  /* 三态条 */
  .states {{ display:flex; gap:12px; }}
  .st {{ flex:1; border-radius:10px; padding:10px 12px; }}
  .st b {{ display:block; font-size:15px; margin-bottom:3px; }}
  .st span {{ font-size:12px; line-height:1.45; display:block; }}
  .st.g {{ background:#eef8f1; border:1px solid #bfe0c8; }} .st.g b {{ color:#22703c; }}
  .st.o {{ background:#fdf6ec; border:1px solid #ecd3ac; }} .st.o b {{ color:#a4611a; }}
  .st.r {{ background:#fdf0ee; border:1px solid #eec6bf; }} .st.r b {{ color:#a8352a; }}
  .st span {{ color:#6d7d8c; }}
  /* 右：工程门禁 */
  .gate {{ width:392px; }}
  .grow {{ display:flex; align-items:center; gap:12px; border:1px solid #dde6ee; background:#fff; border-radius:10px;
    padding:13px 15px; margin-bottom:12px; }}
  .grow .ck {{ width:30px; height:30px; border-radius:50%; background:#e3f2e8; color:#22703c; display:grid; place-items:center;
    font-size:16px; font-weight:800; flex-shrink:0; }}
  .grow .tx b {{ display:block; font-size:15px; color:#2c3e50; }}
  .grow .tx span {{ font-size:12.5px; color:#7a8b9c; }}
</style></head><body>
<div class="stage">
  <!-- 左：六场景矩阵 -->
  <div class="panel scen">
    <div class="p-title"><i></i>六类业务场景</div>
    <div class="p-sub">覆盖火情 · 人员 · 用户约束 · 电量 · 库存 · 审批六类关键变化</div>
    <div class="scen-grid">
      <div class="scard"><h4><em>S1</em>一般林地 · 无人</h4><div class="row"><b>输入</b>：一般火情，资源充足</div><div class="row"><b>动作</b>：侦察/灭火/物流编组，输出可控方案与时间窗</div></div>
      <div class="scard"><h4><em>S2</em>发现人员</h4><div class="row"><b>输入</b>：人员确认存在</div><div class="row"><b>动作</b>：支援机疏散引导，灭火机留守保护通道</div></div>
      <div class="scard"><h4><em>S3</em>用户调整</h4><div class="row"><b>输入</b>：限制出动数量 / 改目标时限</div><div class="row"><b>动作</b>：生成新方案版本，资源与时间变化留痕</div></div>
      <div class="scard"><h4><em>S4</em>SOC 不足</h4><div class="row"><b>输入</b>：航程后接近返航阈值</div><div class="row"><b>动作</b>：返航充电或换电、备机接替，返航 SOC ≥ 25%</div></div>
      <div class="scard"><h4><em>S5</em>库存不足</h4><div class="row"><b>输入</b>：药剂或备用电池不足</div><div class="row"><b>动作</b>：输出资源缺口与不可控结论，不给虚假时间窗</div></div>
      <div class="scard"><h4><em>S6</em>拒绝方案</h4><div class="row"><b>输入</b>：驳回 / 终止</div><div class="row"><b>动作</b>：释放资源锁并归档，原因必填留痕</div></div>
    </div>
  </div>
  <!-- 中：三组代表结果 -->
  <div class="panel" style="flex:1; display:flex; flex-direction:column;">
    <div class="p-title"><i></i>三组代表结果（真实重跑数据）</div>
    <div class="p-sub">曲线为冻结场景当日重跑的轮次账本：FLP = 火情处置负荷</div>
    <div class="chartbox">
      <h5>① 正常小火：逐轮下降直至扑灭归档</h5>
      <div class="cap">初始 45 FLP · 8 架出动 · 每轮压制远超自然增长</div>
      <svg width="100%" height="200" viewBox="0 0 400 200" preserveAspectRatio="xMidYMid meet">{a_bars}
        <text x="24" y="40" font-size="12.5" fill="#8a99a8">FLP</text>
        <line x1="70" y1="170" x2="380" y2="170" stroke="#dde6ee"/>
      </svg>
      <div class="legend"><span><i style="background:#c9d9ea"></i>轮前 FLP</span><span><i style="background:#1b5fa8"></i>轮后 FLP</span></div>
    </div>
    <div class="chartbox" style="flex:1">
      <h5>② 补给间歇：压制轮下降 · 补给轮回升</h5>
      <div class="cap">600 m² 场景限 2 架出动 · 12 轮呈「降-降-增」周期 · 无虚假单调下降</div>
      <svg width="100%" height="{H + 26}" viewBox="0 0 {W} {H + 26}" preserveAspectRatio="xMidYMid meet">
        <line x1="36" y1="18" x2="36" y2="{H - 24}" stroke="#dde6ee"/>
        <line x1="36" y1="{H - 24}" x2="{W - 8}" y2="{H - 24}" stroke="#dde6ee"/>
        <polyline points="{nat_pts}" fill="none" stroke="#c4a94e" stroke-width="2" stroke-dasharray="4 4"/>
        <polyline points="{before_pts}" fill="none" stroke="#c9d9ea" stroke-width="2.5"/>
        <polyline points="{after_pts}" fill="none" stroke="#1b5fa8" stroke-width="2.5"/>
        {marks}{strip}
        <text x="14" y="30" font-size="12" fill="#8a99a8">FLP</text>
      </svg>
      <div class="legend">
        <span><i style="background:#c9d9ea"></i>轮前</span><span><i style="background:#1b5fa8"></i>轮后</span>
        <span><i style="background:#c4a94e"></i>自然增长（不压制对照）</span>
        <span><i style="background:#d96a2b"></i>▲ 回升轮</span>
        <span>底条相位：</span><span><i style="background:#2f8f5b"></i>作业</span><span><i style="background:#4a90d9"></i>补给</span><span><i style="background:#d9a24a"></i>充电</span>
      </div>
    </div>
    <div class="states">
      <div class="st g"><b>可控 · A</b><span>45 FLP → 2 轮扑灭归档，给出处置时间窗</span></div>
      <div class="st o"><b>可维持压制 · B</b><span>压制强于增长但余量有限，诚实标注「可维持」</span></div>
      <div class="st r"><b>不可控 · C</b><span>7200 FLP 大火：压制能力不足，输出缺口原因，请求增援</span></div>
    </div>
  </div>
  <!-- 右：工程门禁 -->
  <div class="panel gate">
    <div class="p-title"><i></i>工程验证门禁（当日实跑）</div>
    <div class="p-sub">同一代码冻结版 · 命令输出可复核</div>
    <div class="grow"><div class="ck">✓</div><div class="tx"><b>规则回归 pytest 193 项全过</b><span>含统一分钟推进一致性 / 资源守恒 / 零增长语义</span></div></div>
    <div class="grow"><div class="ck">✓</div><div class="tx"><b>接口与构建门禁通过</b><span>后端语法检查 · 前端生产构建零错误</span></div></div>
    <div class="grow"><div class="ck">✓</div><div class="tx"><b>浏览器场景 R1-R23 全过</b><span>23 轮 Playwright 场景 · 六场景验收含在内</span></div></div>
    <div class="grow"><div class="ck">✓</div><div class="tx"><b>视觉模型评测单独引用</b><span>自训 YOLO11n · D-Fire 官方测试集 mAP50 0.665 · 单帧 1.4ms</span></div></div>
    <div class="grow" style="border-style:dashed; background:#fbfcfe;"><div class="ck" style="background:#eef2f6; color:#5c7186;">i</div><div class="tx"><b>平台规则测试 ≠ 模型准确率</b><span>功能通过与识别精度分列表述，不互相替代</span></div></div>
  </div>
</div>
</body></html>"""

out = ROOT / "docs" / "pdf-assets" / "fig5-2.html"
out.write_text(html, encoding="utf-8")
print("written", out)

from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1680, "height": 850}, device_scale_factor=2)
    pg.goto(out.as_uri())
    pg.wait_for_timeout(500)
    pg.screenshot(path=str(ROOT / "docs" / "pdf-assets" / "fig5-2.png"))
    b.close()
print("rendered fig5-2.png")
