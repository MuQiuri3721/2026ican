# -*- coding: utf-8 -*-
"""图3-5 合成：战术地图截图为主体 + R/E/S 子群职责标签与航线示意 → 截图。
底图 1000×723 → 显示 1620×1171（1.62 倍）；火点标记显示坐标 ≈(982, 669)。
从项目根运行：python docs/pdf-assets/build_fig3_5.py
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ASSETS = Path(__file__).resolve().parent

HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
* { margin:0; padding:0; box-sizing:border-box; font-family:"Microsoft YaHei","SimHei",sans-serif; }
body { width:1680px; height:1330px; position:relative; background:#0d1622; overflow:hidden; }
.map { position:absolute; left:30px; top:24px; width:1620px; border-radius:10px; }
.ov { position:absolute; }
.lbl { background:rgba(13,22,34,.9); border-radius:9px; padding:7px 13px; font-size:16.5px; font-weight:700; color:#fff; border:1.5px solid; backdrop-filter:blur(2px); }
.lbl small { display:block; font-weight:400; font-size:12.5px; color:#c9d6e2; }
.legend { position:absolute; left:1372px; top:170px; background:rgba(13,22,34,.92); border:1.5px solid #3d4c5c; border-radius:10px; padding:10px 16px; font-size:14.5px; color:#e8eef4; }
.legend div { margin:4px 0; }
.sw { display:inline-block; width:34px; height:0; border-top:3.5px solid; vertical-align:middle; margin-right:8px; }
.dash { border-top-style:dashed; }
.foot { position:absolute; left:30px; top:1288px; width:1620px; text-align:center; font-size:14.5px; color:#aebdcb; }
</style></head><body>
  <img class="map" src="fig3-5-map.png">

  <!-- 侦察监视环（蓝虚线，火点周围 982,669） -->
  <div class="ov" style="left:1195px;top:817px;width:230px;height:150px;border:3px dashed #4da3ff;border-radius:50%;opacity:.85;"></div>

  <!-- R 侦察子群 -->
  <div class="ov lbl" style="left:1080px;top:724px;border-color:#4da3ff;">
    R1 / R2 · 侦察子群<small>主监测 + 高风险复核 · 图像回传</small>
  </div>
  <svg class="ov" style="left:1120px;top:760px;" width="120" height="80">
    <line x1="60" y1="46" x2="106" y2="86" stroke="#4da3ff" stroke-width="3"/>
  </svg>

  <!-- E 灭火子群（橙，右侧压制轴线指向火点） -->
  <div class="ov lbl" style="left:1240px;top:960px;border-color:#ff8c42;">
    E1–E6 · 灭火子群<small>分批压制 · 重点热点 · 通道保护</small>
  </div>
  <svg class="ov" style="left:1240px;top:905px;" width="70" height="46">
    <line x1="6" y1="8" x2="74" y2="42" stroke="#ff8c42" stroke-width="3.5"/>
    <polygon points="74,42 56,34 66,22" fill="#ff8c42"/>
  </svg>

  <!-- S 支援子群（紫，下方补给接替） -->
  <div class="ov lbl" style="left:820px;top:1062px;border-color:#b085f5;">
    S1–S4 · 支援子群<small>通信中继 · 疏散引导 · 药剂电池运输</small>
  </div>
  <svg class="ov" style="left:940px;top:1062px;" width="90" height="56">
    <line x1="46" y1="6" x2="20" y2="86" stroke="#b085f5" stroke-width="3" stroke-dasharray="9 7"/>
    <polygon points="20,86 20,66 36,76" fill="#b085f5"/>
  </svg>

  <!-- 错峰补给说明（紫虚线框，指向蓄水池方向） -->
  <div class="ov lbl" style="left:200px;top:1105px;border-color:#b085f5;border-style:dashed;">
    错峰返航 · 取水补给 · 接替<small>补给间歇允许短时回升 · 后备机接替继续压制</small>
  </div>
  <svg class="ov" style="left:475px;top:1115px;" width="130" height="40">
    <line x1="6" y1="20" x2="112" y2="20" stroke="#b085f5" stroke-width="3" stroke-dasharray="9 7"/>
    <polygon points="124,20 106,12 106,28" fill="#b085f5"/>
  </svg>

  <div class="legend">
    <b style="color:#fff;font-size:15.5px;">图例</b>
    <div><span class="sw" style="border-color:#4da3ff;"></span>侦察监视（R）</div>
    <div><span class="sw" style="border-color:#ff8c42;"></span>压制任务线（E）</div>
    <div><span class="sw dash" style="border-color:#b085f5;"></span>补给 / 接替（S）</div>
    <div style="font-size:12.5px;color:#9fb2c4;margin-top:6px;">底图：高德卫星 · 等高线<br>火点与取水路线为系统真实渲染</div>
  </div>

  <div class="foot">
    12 架无人机（2+6+4）由确定性调度方案分配任务：每架独立记录位置 · SOC · 机载药剂 · 状态（flying / working / returning / servicing），分钟核心同步更新消耗与库存
  </div>
</body></html>"""

out = ASSETS / "fig3-5.html"
out.write_text(HTML, encoding="utf-8")
print("written", out)

from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1680, "height": 1330}, device_scale_factor=2)
    pg.goto(out.as_uri())
    pg.wait_for_timeout(600)
    pg.screenshot(path=str(ASSETS / "fig3-5.png"))
    b.close()
print("rendered fig3-5.png")
