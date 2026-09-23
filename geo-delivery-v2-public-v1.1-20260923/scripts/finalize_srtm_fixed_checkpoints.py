#!/usr/bin/env python3
"""Create and validate the 10 fixed SRTM delivery checkpoints."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.warp import transform
from shapely.geometry import Point, mapping, shape
from shapely.ops import transform as shapely_transform


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
DATA = ROOT / "data/nanjing/srtm"
QA = ROOT / "qa"

RASTERS = {
    "dem": DATA / "nanjing_srtmgl1_003_30m_epsg32650_dem.tif",
    "slope": DATA / "nanjing_srtmgl1_003_30m_epsg32650_slope.tif",
    "aspect": DATA / "nanjing_srtmgl1_003_30m_epsg32650_aspect.tif",
}

CHECKPOINTS = [
    {
        "point_id": "NJ-MTN-01",
        "region_group": "nanjing",
        "point_type": "typical_mountain_zijin",
        "longitude": 118.843000,
        "latitude": 32.070000,
        "expected_region": "Nanjing confirmed AOI",
        "expected_data_status": "VALID_DATA",
        "rule": "mountain",
        "notes": "紫金山典型山地点；固定验收坐标，不代表山峰法定标志点。",
    },
    {
        "point_id": "NJ-MTN-02",
        "region_group": "nanjing",
        "point_type": "western_mountain",
        "longitude": 118.400000,
        "latitude": 32.050000,
        "expected_region": "Nanjing confirmed AOI",
        "expected_data_status": "VALID_DATA",
        "rule": "mountain",
        "notes": "南京西部山地覆盖与起伏检查点。",
    },
    {
        "point_id": "NJ-URBAN-01",
        "region_group": "nanjing",
        "point_type": "urban_flat",
        "longitude": 118.797000,
        "latitude": 32.060000,
        "expected_region": "Nanjing confirmed AOI",
        "expected_data_status": "VALID_DATA",
        "rule": "flat",
        "notes": "南京主城区平缓地形检查点。",
    },
    {
        "point_id": "NJ-LOW-01",
        "region_group": "nanjing",
        "point_type": "southern_lowland",
        "longitude": 118.800000,
        "latitude": 31.300000,
        "expected_region": "Nanjing confirmed AOI",
        "expected_data_status": "VALID_DATA",
        "rule": "flat",
        "notes": "南京南部低地有效覆盖检查点。",
    },
    {
        "point_id": "NJ-WATER-01",
        "region_group": "nanjing",
        "point_type": "water_surface_xuanwu_lake",
        "longitude": 118.796000,
        "latitude": 32.080000,
        "expected_region": "Nanjing confirmed AOI",
        "expected_data_status": "VALID_DATA",
        "rule": "flat",
        "notes": "玄武湖水域像元及低坡度稳定性检查点。",
    },
    {
        "point_id": "NJ-EAST-01",
        "region_group": "nanjing",
        "point_type": "eastern_boundary_interior",
        "longitude": 119.217900,
        "latitude": 31.620700,
        "expected_region": "Nanjing confirmed AOI",
        "expected_data_status": "VALID_DATA",
        "rule": "valid",
        "notes": "南京东部边缘内侧覆盖检查点。",
    },
    {
        "point_id": "NJ-WEST-01",
        "region_group": "nanjing",
        "point_type": "western_boundary_interior",
        "longitude": 118.368040,
        "latitude": 31.941460,
        "expected_region": "Nanjing confirmed AOI",
        "expected_data_status": "VALID_DATA",
        "rule": "valid",
        "notes": "南京西部边缘内侧覆盖检查点。",
    },
    {
        "point_id": "PLAN-01",
        "region_group": "planning_area",
        "point_type": "planning_yuntai_representative",
        "longitude": 119.316664,
        "latitude": 34.658790,
        "expected_region": "planning_yuntai",
        "expected_data_status": "NO_DATA_OUTSIDE_DELIVERY",
        "rule": "outside",
        "notes": "云台山规划展示区代表点；应明确返回南京SRTM交付范围外。",
    },
    {
        "point_id": "JS-OTHER-01",
        "region_group": "jiangsu_non_demo",
        "point_type": "jiangsu_outside_nanjing",
        "longitude": 117.200000,
        "latitude": 34.300000,
        "expected_region": "Jiangsu outside Nanjing delivery",
        "expected_data_status": "NO_DATA_OUTSIDE_DELIVERY",
        "rule": "outside",
        "notes": "江苏省内南京外检查点；不能从南京交付栅格伪造数值。",
    },
    {
        "point_id": "OUT-01",
        "region_group": "outside_region",
        "point_type": "outside_jiangsu",
        "longitude": 121.470000,
        "latitude": 31.230000,
        "expected_region": "Outside Jiangsu",
        "expected_data_status": "NO_DATA_OUTSIDE_DELIVERY",
        "rule": "outside",
        "notes": "省外检查点；应明确返回南京SRTM交付范围外。",
    },
]


def load_geometry(path: Path, property_name: str | None = None, value: str | None = None):
    collection = json.loads(path.read_text(encoding="utf-8-sig"))
    features = collection["features"]
    if property_name is not None:
        features = [f for f in features if f.get("properties", {}).get(property_name) == value]
    if len(features) != 1:
        raise RuntimeError(f"Expected one geometry in {path}, found {len(features)}")
    return shape(features[0]["geometry"])


def read_hgt(lon: float, lat: float) -> int | None:
    if not (118.0 <= lon <= 119.0 and 32.0 <= lat <= 33.0):
        return None
    path = PROJECT_ROOT / "backend/N32E118.hgt"
    if not path.exists():
        return None
    grid = np.memmap(path, dtype=">i2", mode="r", shape=(3601, 3601))
    row = round((33.0 - lat) * 3600)
    col = round((lon - 118.0) * 3600)
    value = int(grid[row, col])
    return None if value == -32768 else value


def sample_value(dataset: rasterio.io.DatasetReader, lon: float, lat: float) -> float | None:
    xs, ys = transform("EPSG:4326", dataset.crs, [lon], [lat])
    value = float(next(dataset.sample([(xs[0], ys[0])]))[0])
    if value == dataset.nodata or not np.isfinite(value):
        return None
    return value


def make_map(records, aoi, buffer_geom, jiangsu, yuntai, dem_path: Path, output: Path) -> None:
    with rasterio.open(dem_path) as dem:
        scale = 10
        reduced = dem.read(
            1,
            out_shape=(max(1, dem.height // scale), max(1, dem.width // scale)),
            masked=True,
        )
        bounds = dem.bounds
        transformer = Transformer.from_crs("EPSG:4326", dem.crs, always_xy=True)
        project = lambda x, y, z=None: transformer.transform(x, y)
        aoi_m = shapely_transform(project, aoi)
        buffer_m = shapely_transform(project, buffer_geom)

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 7), constrained_layout=True)
        ax1.imshow(
            reduced,
            extent=[bounds.left, bounds.right, bounds.bottom, bounds.top],
            origin="upper",
            cmap="terrain",
        )
        for geom, color, label, width in [
            (buffer_m, "#f97316", "Nanjing + 5 km", 1.2),
            (aoi_m, "#dc2626", "Nanjing AOI", 1.5),
        ]:
            geoms = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
            first = True
            for part in geoms:
                x, y = part.exterior.xy
                ax1.plot(x, y, color=color, linewidth=width, label=label if first else None)
                first = False
        label_offsets = {
            "NJ-MTN-01": (6, 14),
            "NJ-MTN-02": (6, 5),
            "NJ-URBAN-01": (6, -16),
            "NJ-LOW-01": (6, 5),
            "NJ-WATER-01": (6, 15),
            "NJ-EAST-01": (6, 5),
            "NJ-WEST-01": (6, 5),
        }
        for row in records[:7]:
            x, y = transformer.transform(row["longitude"], row["latitude"])
            ax1.scatter(x, y, s=48, c="#111827", edgecolors="white", linewidths=0.9, zorder=4)
            ax1.annotate(
                row["point_id"],
                (x, y),
                xytext=label_offsets[row["point_id"]],
                textcoords="offset points",
                fontsize=7,
                bbox={"facecolor": "white", "alpha": 0.65, "edgecolor": "none", "pad": 1},
            )
        ax1.set_title("Nanjing fixed valid-data checkpoints")
        ax1.set_xlabel("EPSG:32650 easting (m)")
        ax1.set_ylabel("EPSG:32650 northing (m)")
        ax1.legend(loc="lower left", fontsize=8)

    for geom, color, label in [(jiangsu, "#2563eb", "Jiangsu"), (yuntai, "#16a34a", "Yuntai planning region")]:
        geoms = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
        first = True
        for part in geoms:
            x, y = part.exterior.xy
            ax2.plot(x, y, color=color, linewidth=1.3, label=label if first else None)
            first = False
    point_colors = {"PLAN-01": "#16a34a", "JS-OTHER-01": "#7c3aed", "OUT-01": "#dc2626"}
    point_markers = {"PLAN-01": "o", "JS-OTHER-01": "s", "OUT-01": "X"}
    for row in records[7:]:
        ax2.scatter(
            row["longitude_numeric"],
            row["latitude_numeric"],
            s=100,
            c=point_colors[row["point_id"]],
            marker=point_markers[row["point_id"]],
            edgecolors="white",
            linewidths=1.2,
            zorder=5,
        )
        ax2.annotate(
            row["point_id"],
            (row["longitude_numeric"], row["latitude_numeric"]),
            xytext=(7, 6),
            textcoords="offset points",
            fontsize=9,
            fontweight="bold",
            bbox={"facecolor": "white", "alpha": 0.8, "edgecolor": "none", "pad": 1.5},
        )
    ax2.set_xlim(116.7, 121.8)
    ax2.set_ylim(30.5, 35.2)
    ax2.set_aspect("equal", adjustable="box")
    ax2.set_title("Expected out-of-delivery checkpoints")
    ax2.set_xlabel("Longitude (EPSG:4326)")
    ax2.set_ylabel("Latitude (EPSG:4326)")
    ax2.legend(loc="lower left", fontsize=8)
    fig.suptitle("SRTM fixed checkpoint QA", fontsize=15)
    fig.savefig(output, dpi=180)
    plt.close(fig)


def promote_authoritative_metadata() -> None:
    """Promote SRTM QA only after all ten fixed checkpoints pass."""
    path = DATA / "nanjing_srtm_metadata.csv"
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    required = {"qa_status", "technical_qa_status", "fixed_checkpoint_qa_status", "overall_qa_status"}
    if not required.issubset(fieldnames):
        raise RuntimeError(f"Authoritative metadata lacks QA fields: {sorted(required - set(fieldnames))}")
    for row in rows:
        row["qa_status"] = "PASS"
        row["technical_qa_status"] = "PASS"
        row["fixed_checkpoint_qa_status"] = "PASS"
        row["overall_qa_status"] = "PASS"
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    QA.mkdir(parents=True, exist_ok=True)
    boundary_path = DATA / "nanjing_srtm_boundaries.geojson"
    aoi = load_geometry(boundary_path, "boundary_type", "confirmed_aoi")
    buffer_geom = load_geometry(boundary_path, "boundary_type", "delivery_extent_aoi_plus_5km")
    jiangsu = load_geometry(ROOT / "scripts/jiangsu_province_boundary_wgs84.geojson")
    yuntai = load_geometry(
        ROOT / "data/nanjing/planning_regions/planning_regions_overview.geojson",
        "region_id",
        "planning_yuntai",
    )

    datasets = {name: rasterio.open(path) for name, path in RASTERS.items()}
    records = []
    try:
        for item in CHECKPOINTS:
            lon, lat = item["longitude"], item["latitude"]
            point = Point(lon, lat)
            inside_aoi = aoi.covers(point)
            inside_buffer = buffer_geom.covers(point)
            inside_jiangsu = jiangsu.covers(point)
            inside_planning = yuntai.covers(point)
            dem = sample_value(datasets["dem"], lon, lat)
            slope = sample_value(datasets["slope"], lon, lat)
            aspect = sample_value(datasets["aspect"], lon, lat)
            hgt = read_hgt(lon, lat)
            difference = None if hgt is None or dem is None else abs(dem - hgt)

            if dem is not None and slope is not None and aspect is not None:
                actual_status = "VALID_DATA"
            else:
                actual_status = "NO_DATA_OUTSIDE_DELIVERY"

            checks = [actual_status == item["expected_data_status"]]
            if item["rule"] != "outside":
                checks.extend([
                    inside_aoi,
                    inside_buffer,
                    dem is not None and -200 <= dem <= 1000,
                    slope is not None and 0 <= slope <= 90,
                    aspect is not None and 0 <= aspect < 360,
                ])
                if item["rule"] == "mountain":
                    checks.append(slope is not None and slope >= 5)
                if item["rule"] == "flat":
                    checks.append(slope is not None and slope <= 5)
                if difference is not None:
                    checks.append(difference <= 5)
            else:
                checks.extend([not inside_aoi, not inside_buffer, dem is None, slope is None, aspect is None])
                if item["point_id"] == "PLAN-01":
                    checks.extend([inside_jiangsu, inside_planning])
                elif item["point_id"] == "JS-OTHER-01":
                    checks.extend([inside_jiangsu, not inside_planning])
                elif item["point_id"] == "OUT-01":
                    checks.append(not inside_jiangsu)

            record = {
                "point_id": item["point_id"],
                "region_group": item["region_group"],
                "point_type": item["point_type"],
                "longitude": f"{lon:.6f}",
                "latitude": f"{lat:.6f}",
                "expected_region": item["expected_region"],
                "expected_data_status": item["expected_data_status"],
                "actual_data_status": actual_status,
                "reference_source": "backend/N32E118.hgt" if hgt is not None else "spatial extent and raster NoData check",
                "reference_elevation_m": "" if hgt is None else str(hgt),
                "gee_elevation_m": "" if dem is None else f"{dem:.0f}",
                "absolute_difference_m": "" if difference is None else f"{difference:.0f}",
                "slope_degree": "" if slope is None else f"{slope:.0f}",
                "aspect_degree": "" if aspect is None else f"{aspect:.0f}",
                "inside_confirmed_aoi": str(inside_aoi).upper(),
                "inside_5km_buffer": str(inside_buffer).upper(),
                "inside_jiangsu": str(inside_jiangsu).upper(),
                "inside_expected_planning_region": str(inside_planning).upper(),
                "qa_result": "PASS" if all(checks) else "FAIL",
                "notes": item["notes"],
                "longitude_numeric": lon,
                "latitude_numeric": lat,
            }
            records.append(record)
    finally:
        for dataset in datasets.values():
            dataset.close()

    csv_fields = [
        "point_id", "region_group", "point_type", "longitude", "latitude",
        "expected_region", "expected_data_status", "actual_data_status",
        "reference_source", "reference_elevation_m", "gee_elevation_m",
        "absolute_difference_m", "slope_degree", "aspect_degree",
        "inside_confirmed_aoi", "inside_5km_buffer", "inside_jiangsu",
        "inside_expected_planning_region", "qa_result", "notes",
    ]
    csv_path = QA / "srtm_check_points.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=csv_fields)
        writer.writeheader()
        for row in records:
            writer.writerow({key: row[key] for key in csv_fields})

    geojson = {
        "type": "FeatureCollection",
        "name": "srtm_fixed_checkpoints",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "features": [
            {
                "type": "Feature",
                "properties": {key: row[key] for key in csv_fields if key not in {"longitude", "latitude"}},
                "geometry": mapping(Point(row["longitude_numeric"], row["latitude_numeric"])),
            }
            for row in records
        ],
    }
    geojson_path = QA / "srtm_fixed_checkpoints.geojson"
    geojson_path.write_text(json.dumps(geojson, ensure_ascii=False, indent=2), encoding="utf-8")

    map_path = QA / "srtm_fixed_checkpoints_map.png"
    make_map(records, aoi, buffer_geom, jiangsu, yuntai, RASTERS["dem"], map_path)

    failures = [row["point_id"] for row in records if row["qa_result"] != "PASS"]
    if not failures:
        promote_authoritative_metadata()
    print(json.dumps({
        "csv": str(csv_path),
        "geojson": str(geojson_path),
        "map": str(map_path),
        "checkpoint_count": len(records),
        "pass_count": len(records) - len(failures),
        "failures": failures,
    }, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
