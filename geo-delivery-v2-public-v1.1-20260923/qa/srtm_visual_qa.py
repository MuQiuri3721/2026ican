"""Render a read-only visual QA overview of the Nanjing SRTM delivery.

Run with a Python environment that has rasterio, numpy and matplotlib:
    python qa/srtm_visual_qa.py
"""

from pathlib import Path
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import transform_geom


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "nanjing" / "srtm"
OUTPUT = ROOT / "qa" / "nanjing_srtm_visual_qa.png"


def plot_polygon(ax, geometry, color, linewidth, label):
    projected = transform_geom("EPSG:4326", "EPSG:32650", geometry)
    if projected["type"] == "Polygon":
        polygons = [projected["coordinates"]]
    else:
        polygons = projected["coordinates"]
    first = True
    for polygon in polygons:
        for ring in polygon:
            xy = np.asarray(ring)
            ax.plot(
                xy[:, 0],
                xy[:, 1],
                color=color,
                linewidth=linewidth,
                label=label if first else None,
                alpha=0.9,
            )
            first = False


with (DATA / "nanjing_srtm_boundaries.geojson").open(
    encoding="utf-8"
) as file:
    boundaries = json.load(file)["features"]

layers = [
    ("dem", "Elevation (m)", "terrain", Resampling.average, None, None),
    ("slope", "Slope (degree)", "magma", Resampling.average, 0, 45),
    ("aspect", "Aspect (degree)", "twilight", Resampling.nearest, 0, 360),
]
fig, axes = plt.subplots(1, 3, figsize=(16, 9), constrained_layout=True)

for ax, (name, title, palette, resampling, low, high) in zip(axes, layers):
    path = DATA / f"nanjing_srtmgl1_003_30m_epsg32650_{name}.tif"
    with rasterio.open(path) as raster:
        data = raster.read(
            1,
            out_shape=(1000, 575),
            masked=True,
            resampling=resampling,
        )
        limits = (
            raster.bounds.left,
            raster.bounds.right,
            raster.bounds.bottom,
            raster.bounds.top,
        )
        image = ax.imshow(
            data,
            extent=limits,
            origin="upper",
            cmap=palette,
            vmin=low,
            vmax=high,
        )

    plot_polygon(
        ax,
        boundaries[0]["geometry"],
        "#00d0ff",
        0.8,
        "Municipal boundary",
    )
    plot_polygon(
        ax,
        boundaries[1]["geometry"],
        "#ff3b3b",
        0.6,
        "Boundary + 5 km",
    )
    ax.set_title(title)
    ax.set_xlabel("Easting, EPSG:32650 (m)")
    ax.set_ylabel("Northing (m)")
    ax.set_aspect("equal")
    ax.ticklabel_format(style="plain", useOffset=False)
    fig.colorbar(image, ax=ax, fraction=0.038, pad=0.015)

axes[0].legend(loc="lower left", fontsize=8)
fig.suptitle("Nanjing SRTM terrain delivery: visual QA", fontsize=14)
fig.savefig(OUTPUT, dpi=160)
print(OUTPUT)
