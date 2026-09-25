# -*- coding: utf-8 -*-
"""图3-3 证据插图：南京 SRTM 高程/坡度/坡向三联图（中文版）。
读 geo-delivery-v2-public-v1.0 离线包 DEM 成果重绘，标题中文化，
并框出紫金山示范林区任务点局部范围（32.0688°N, 118.8432°E 附近）。
从项目根运行：python docs/pdf-assets/build_fig3_evidence.py
"""
import sys
from pathlib import Path

import numpy as np
import rasterio
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib import font_manager

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "geo-delivery-v2-public-v1.0-20260922" / "data" / "nanjing" / "srtm"
OUT = ROOT / "docs" / "pdf-assets" / "fig3-3-srtm-zh.png"

# 中文字体（黑体，与正文排版一致）
for cand in (r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\msyh.ttc"):
    if Path(cand).exists():
        font_manager.fontManager.addfont(cand)
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=cand).get_name()
        break
plt.rcParams["axes.unicode_minus"] = False

# 紫金山示范林区任务点（32.0688°N, 118.8432°E）在 EPSG:32650 下的局部框（米）
ZJX = (652000, 3538000, 688000, 3572000)  # (xmin, ymin, xmax, ymax) 局部框

bands = [
    ("nanjing_srtmgl1_003_30m_epsg32650_dem.tif", "高程（米）", "terrain", "高程"),
    ("nanjing_srtmgl1_003_30m_epsg32650_slope.tif", "坡度（度）", "magma", "坡度"),
    ("nanjing_srtmgl1_003_30m_epsg32650_aspect.tif", "坡向（度）", "twilight_shifted", "坡向"),
]

fig, axes = plt.subplots(1, 3, figsize=(16.5, 6.4), dpi=150)
fig.suptitle("南京 SRTM 地形成果（SRTMGL1 v003 · 30 米 · EPSG:32650）", fontsize=17, y=0.985)

for ax, (fname, title, cmap, zlabel) in zip(axes, bands):
    with rasterio.open(SRC / fname) as ds:
        data = ds.read(1)
        data = np.where(data == ds.nodata, np.nan, data) if ds.nodata is not None else data
        xmin, ymin, xmax, ymax = ds.bounds
        extent = [xmin / 1000, xmax / 1000, ymin / 1000, ymax / 1000]  # 千米
    im = ax.imshow(data, extent=extent, origin="upper", cmap=cmap)
    ax.set_title(title, fontsize=14)
    ax.set_xlabel("东西坐标 · EPSG:32650（千米）", fontsize=10)
    ax.set_ylabel("南北坐标（千米）", fontsize=10)
    ax.tick_params(labelsize=8.5)
    cb = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    cb.set_label(zlabel, fontsize=10)
    # 紫金山任务点局部框
    zx0, zy0, zx1, zy1 = ZJX[0] / 1000, ZJX[1] / 1000, ZJX[2] / 1000, ZJX[3] / 1000
    ax.add_patch(Rectangle((zx0, zy0), zx1 - zx0, zy1 - zy0, fill=False, edgecolor="#d62828", lw=2.2))
    ax.text((zx0 + zx1) / 2, zy0 + 6, "紫金山示范林区", ha="center", va="bottom",
            fontsize=11.5, color="#ffffff", fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.25", fc="#d62828", ec="none", alpha=0.92))

fig.tight_layout(rect=(0, 0, 1, 0.955))
fig.savefig(OUT, dpi=150)
print("written", OUT)
