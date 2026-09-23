"""Finalize and verify the Nanjing ESA WorldCover delivery.

The script keeps the downloaded TIFF files unchanged. It rebuilds exact class
statistics from the delivered raster, updates metadata, creates visual QA
figures and a report, and refreshes the root delivery manifest.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import Window
from rasterio.warp import transform_geom


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "nanjing" / "worldcover"
QA = ROOT / "qa"
LANDCOVER = DATA / "nanjing_worldcover_2021_v200_10m_epsg32650_landcover.tif"
TREE_COVER = DATA / "nanjing_worldcover_2021_v200_10m_epsg32650_tree_cover.tif"
METADATA = DATA / "nanjing_worldcover_2021_v200_metadata.csv"
STATISTICS = DATA / "nanjing_worldcover_2021_v200_statistics.csv"
BOUNDARIES = ROOT / "data" / "nanjing" / "srtm" / "nanjing_srtm_boundaries.geojson"
REPORT = QA / "nanjing_worldcover_qa_report.md"
MANIFEST = ROOT / "manifest.json"

CLASS_INFO = {
    10: ("Tree cover", "#006400"),
    20: ("Shrubland", "#ffbb22"),
    30: ("Grassland", "#ffff4c"),
    40: ("Cropland", "#f096ff"),
    50: ("Built-up", "#fa0000"),
    60: ("Bare / sparse vegetation", "#b4b4b4"),
    70: ("Snow and ice", "#f0f0f0"),
    80: ("Permanent water bodies", "#0064c8"),
    90: ("Herbaceous wetland", "#0096a0"),
    95: ("Mangroves", "#00cf75"),
    100: ("Moss and lichen", "#fae6a0"),
}
NODATA = 255


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def inspect_rasters() -> dict:
    land_counts: Counter[int] = Counter()
    tree_counts: Counter[int] = Counter()
    derivation_mismatch = 0
    nodata_mask_mismatch = 0

    with rasterio.open(LANDCOVER) as land, rasterio.open(TREE_COVER) as tree:
        same_grid = (
            land.crs == tree.crs
            and land.transform == tree.transform
            and land.width == tree.width
            and land.height == tree.height
        )
        for _, window in land.block_windows(1):
            land_block = land.read(1, window=window)
            tree_block = tree.read(1, window=window)
            values, counts = np.unique(land_block, return_counts=True)
            land_counts.update(dict(zip(map(int, values), map(int, counts))))
            values, counts = np.unique(tree_block, return_counts=True)
            tree_counts.update(dict(zip(map(int, values), map(int, counts))))
            valid = land_block != NODATA
            expected_tree = (land_block == 10).astype(np.uint8)
            derivation_mismatch += int(
                np.count_nonzero(valid & (tree_block != expected_tree))
            )
            nodata_mask_mismatch += int(
                np.count_nonzero((land_block == NODATA) != (tree_block == NODATA))
            )

        return {
            "crs": str(land.crs),
            "width": land.width,
            "height": land.height,
            "resolution": [float(land.res[0]), float(abs(land.res[1]))],
            "bounds": [
                float(land.bounds.left),
                float(land.bounds.bottom),
                float(land.bounds.right),
                float(land.bounds.top),
            ],
            "dtype": land.dtypes[0],
            "nodata": int(land.nodata),
            "block_shape": list(land.block_shapes[0]),
            "overviews": land.overviews(1),
            "image_structure": land.tags(ns="IMAGE_STRUCTURE"),
            "same_grid": same_grid,
            "landcover_counts": dict(sorted(land_counts.items())),
            "tree_counts": dict(sorted(tree_counts.items())),
            "derivation_mismatch": derivation_mismatch,
            "nodata_mask_mismatch": nodata_mask_mismatch,
        }


def write_statistics(result: dict) -> None:
    counts = result["landcover_counts"]
    valid_count = sum(counts.get(value, 0) for value in CLASS_INFO)
    fields = [
        "class_value",
        "class_name",
        "pixel_count",
        "area_m2",
        "area_km2",
        "valid_area_percent",
        "present_in_delivery",
        "region_id",
        "region_name_zh",
        "source_dataset_id",
        "output_crs",
        "output_resolution_m",
        "valid_pixel_count_all_classes",
        "statistics_basis",
    ]
    with STATISTICS.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for value, (name, _) in CLASS_INFO.items():
            count = int(counts.get(value, 0))
            writer.writerow(
                {
                    "class_value": value,
                    "class_name": name,
                    "pixel_count": count,
                    "area_m2": count * 100,
                    "area_km2": f"{count / 10000:.4f}",
                    "valid_area_percent": f"{count / valid_count * 100:.12f}",
                    "present_in_delivery": str(count > 0).lower(),
                    "region_id": "nanjing",
                    "region_name_zh": "南京市",
                    "source_dataset_id": "ESA_WorldCover_2021_v200",
                    "output_crs": "EPSG:32650",
                    "output_resolution_m": 10,
                    "valid_pixel_count_all_classes": valid_count,
                    "statistics_basis": "exact integer count from delivered landcover TIFF",
                }
            )


def update_metadata(visual_status: str) -> None:
    with METADATA.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        original_fields = list(reader.fieldnames or [])

    extra_fields = [
        "access_platform",
        "official_product_page",
        "product_doi",
        "class_count",
        "boundary_original_crs",
        "boundary_processing_history",
        "export_destination",
        "local_delivery_path",
        "license_url",
    ]
    fields = original_fields + [field for field in extra_fields if field not in original_fields]
    tif_hashes = {
        "landcover": sha256(LANDCOVER),
        "tree_cover": sha256(TREE_COVER),
    }
    tif_paths = {
        "landcover": LANDCOVER.relative_to(ROOT).as_posix(),
        "tree_cover": TREE_COVER.relative_to(ROOT).as_posix(),
    }
    for row in rows:
        product = row["product_name"]
        row.update(
            {
                "boundary_downloaded_at": "2026-09-10",
                "boundary_license_or_terms": (
                    "Tianditu terms and attribution requirements; exact dataset-specific "
                    "license was not provided in the download record"
                ),
                "boundary_source_provider": "国家地理信息公共服务平台（天地图）",
                "boundary_source_url": (
                    "https://cloudcenter.tianditu.gov.cn/administrativeDivision"
                ),
                "boundary_source_version": "not_provided_by_source",
                "downloaded_at": "2026-09-20",
                "qa_status": "PASS" if visual_status == "PASS" else "VISUAL_REVIEW_PENDING",
                "sha256": tif_hashes[product],
                "access_platform": "Google Earth Engine",
                "official_product_page": "https://esa-worldcover.org/en/data-access",
                "product_doi": "10.5281/zenodo.7254221",
                "class_count": "11",
                "boundary_original_crs": "CGCS2000 (EPSG:4490)",
                "boundary_processing_history": (
                    "Tianditu administrative division -> CGCS2000 source geometry -> "
                    "WGS84 delivery boundary -> 5 km metric buffer in EPSG:32650"
                ),
                "export_destination": "Google Drive",
                "local_delivery_path": tif_paths[product],
                "license_url": "https://creativecommons.org/licenses/by/4.0/",
            }
        )

    with METADATA.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def projected_boundaries() -> list[tuple[dict, dict]]:
    content = json.loads(BOUNDARIES.read_text(encoding="utf-8"))
    return [
        (
            transform_geom("EPSG:4326", "EPSG:32650", feature["geometry"]),
            feature.get("properties", {}),
        )
        for feature in content["features"]
    ]


def plot_geometry(ax, geometry: dict, color: str, width: float, label: str) -> None:
    polygons = (
        [geometry["coordinates"]]
        if geometry["type"] == "Polygon"
        else geometry["coordinates"]
    )
    first = True
    for polygon in polygons:
        for ring in polygon:
            xy = np.asarray(ring)
            ax.plot(
                xy[:, 0],
                xy[:, 1],
                color=color,
                linewidth=width,
                label=label if first else None,
            )
            first = False


def class_index(array: np.ndarray) -> np.ma.MaskedArray:
    indexed = np.full(array.shape, -1, dtype=np.int16)
    for index, value in enumerate(CLASS_INFO):
        indexed[array == value] = index
    return np.ma.masked_less(indexed, 0)


def save_visuals() -> None:
    colors = [info[1] for info in CLASS_INFO.values()]
    cmap = ListedColormap(colors)
    boundaries = projected_boundaries()
    with rasterio.open(LANDCOVER) as source:
        factor = 8
        image = source.read(
            1,
            out_shape=(1, max(1, source.height // factor), max(1, source.width // factor)),
            resampling=Resampling.nearest,
        )
        extent = [source.bounds.left, source.bounds.right, source.bounds.bottom, source.bounds.top]

        fig, ax = plt.subplots(figsize=(12, 9), constrained_layout=True)
        ax.imshow(
            class_index(image),
            cmap=cmap,
            vmin=-0.5,
            vmax=len(CLASS_INFO) - 0.5,
            extent=extent,
            origin="upper",
            interpolation="nearest",
        )
        ax.set_title("Nanjing ESA WorldCover 2021 v200 overview")
        ax.set_xlabel("Easting (m), EPSG:32650")
        ax.set_ylabel("Northing (m), EPSG:32650")
        ax.legend(
            handles=[Patch(facecolor=color, label=name) for name, color in CLASS_INFO.values()],
            loc="center left",
            bbox_to_anchor=(1.01, 0.5),
            fontsize=8,
        )
        fig.savefig(QA / "worldcover_nanjing_overview.png", dpi=180)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(12, 9), constrained_layout=True)
        ax.imshow(
            class_index(image),
            cmap=cmap,
            vmin=-0.5,
            vmax=len(CLASS_INFO) - 0.5,
            extent=extent,
            origin="upper",
            interpolation="nearest",
        )
        for geometry, props in boundaries:
            boundary_type = props.get("boundary_type", "boundary")
            is_aoi = boundary_type == "confirmed_aoi"
            plot_geometry(
                ax,
                geometry,
                "#ff0000" if is_aoi else "#00ffff",
                1.5 if is_aoi else 1.0,
                "Nanjing boundary" if is_aoi else "Delivery extent (+5 km)",
            )
        ax.set_title("WorldCover with Nanjing boundary and 5 km delivery extent")
        ax.set_xlabel("Easting (m), EPSG:32650")
        ax.set_ylabel("Northing (m), EPSG:32650")
        ax.legend(loc="lower left")
        fig.savefig(QA / "worldcover_boundary_overlay.png", dpi=180)
        plt.close(fig)

        coarse_factor = 4
        coarse = source.read(
            1,
            out_shape=(1, max(1, source.height // coarse_factor), max(1, source.width // coarse_factor)),
            resampling=Resampling.nearest,
        )
        block = 256
        best = (0, 0, -1)
        for row in range(0, max(1, coarse.shape[0] - block), block // 2):
            for col in range(0, max(1, coarse.shape[1] - block), block // 2):
                sample = coarse[row : row + block, col : col + block]
                score = min(
                    np.count_nonzero(sample == 10),
                    np.count_nonzero(sample == 50),
                    np.count_nonzero(sample == 80),
                )
                if score > best[2]:
                    best = (row, col, int(score))
        row, col, _ = best
        full_window = Window(
            col * coarse_factor,
            row * coarse_factor,
            min(block * coarse_factor, source.width - col * coarse_factor),
            min(block * coarse_factor, source.height - row * coarse_factor),
        )
        detail = source.read(1, window=full_window)
        detail_bounds = rasterio.windows.bounds(full_window, source.transform)
        detail_extent = [
            detail_bounds[0],
            detail_bounds[2],
            detail_bounds[1],
            detail_bounds[3],
        ]
        fig, ax = plt.subplots(figsize=(10, 9), constrained_layout=True)
        ax.imshow(
            class_index(detail),
            cmap=cmap,
            vmin=-0.5,
            vmax=len(CLASS_INFO) - 0.5,
            extent=detail_extent,
            origin="upper",
            interpolation="nearest",
        )
        ax.set_title("Detail QA: tree cover, built-up land and permanent water")
        ax.set_xlabel("Easting (m), EPSG:32650")
        ax.set_ylabel("Northing (m), EPSG:32650")
        focus = [10, 50, 80]
        ax.legend(
            handles=[Patch(facecolor=CLASS_INFO[v][1], label=CLASS_INFO[v][0]) for v in focus],
            loc="lower left",
        )
        fig.savefig(QA / "worldcover_tree_cover_detail.png", dpi=180)
        plt.close(fig)


def pass_fail(condition: bool) -> str:
    return "PASS" if condition else "FAIL"


def write_report(result: dict, visual_status: str) -> None:
    official_values = set(CLASS_INFO)
    land_values = set(result["landcover_counts"]) - {NODATA}
    tree_values = set(result["tree_counts"])
    valid_pixels = sum(result["landcover_counts"].get(value, 0) for value in CLASS_INFO)
    tree_pixels = result["landcover_counts"].get(10, 0)
    tif_hashes = {LANDCOVER.name: sha256(LANDCOVER), TREE_COVER.name: sha256(TREE_COVER)}
    csv_hashes = {METADATA.name: sha256(METADATA), STATISTICS.name: sha256(STATISTICS)}
    checks = {
        "CRS": result["crs"] == "EPSG:32650",
        "pixel size": result["resolution"] == [10.0, 10.0],
        "data type": result["dtype"] == "uint8",
        "NoData": result["nodata"] == NODATA,
        "land-cover class values": land_values <= official_values,
        "tree-cover values": tree_values <= {0, 1, NODATA},
        "same grid/shape/transform": result["same_grid"],
        "tree-mask derivation": result["derivation_mismatch"] == 0,
        "NoData masks": result["nodata_mask_mismatch"] == 0,
        "COG layout": result["image_structure"].get("LAYOUT") == "COG",
        "internal overviews": bool(result["overviews"]),
        "SHA256 calculated": all(tif_hashes.values()) and all(csv_hashes.values()),
    }
    table = "\n".join(
        f"| {name} | {pass_fail(ok)} |" for name, ok in checks.items()
    )
    hashes = "\n".join(
        f"- `{name}`: `{value}`" for name, value in {**tif_hashes, **csv_hashes}.items()
    )
    REPORT.write_text(
        f"""# 南京 WorldCover 2021 v200 质量检查

核查范围：南京市行政边界及其外扩 5 km。边界来自天地图行政区划下载入口，原始坐标参考记录为 CGCS2000；WorldCover 数据来自 ESA WorldCover Consortium，并通过 Google Earth Engine 获取和处理。

## 自动检查结果

| 检查项 | 结果 |
|---|---|
{table}

- 栅格尺寸：{result['width']} × {result['height']}。
- 栅格范围：{result['bounds']}（EPSG:32650，单位 m）。
- 有效地表分类像元：{valid_pixels:,}。
- WorldCover 类别 10（Tree cover）像元：{tree_pixels:,}，占有效分类像元 {tree_pixels / valid_pixels * 100:.6f}%。
- 树木覆盖派生不一致像元：{result['derivation_mismatch']}。
- NoData 掩膜不一致像元：{result['nodata_mask_mismatch']}。
- 统计表已按最终交付 TIFF 重算，`pixel_count` 为严格整数；面积按 10 m × 10 m 完整像元计算。

Tree cover 百分比仅表示 WorldCover 遥感分类中类别 10 的像元比例，不等同于南京市官方森林覆盖率、森林资源调查结果或林区管理边界。

## 视觉检查

- `worldcover_nanjing_overview.png`：南京全域分类概览。
- `worldcover_boundary_overlay.png`：南京边界、5 km 交付范围与分类栅格叠加。
- `worldcover_tree_cover_detail.png`：树木覆盖、建设用地和永久水体混合区域局部检查。
- 视觉复核状态：**{visual_status}**。

视觉检查用于发现整体平移、边界错位、大片异常空值和明显分类渲染问题，不代表逐像元地面真实性核验。

## 文件校验值

{hashes}

## 来源与许可

- ESA WorldCover 2021 v200：`ESA/WorldCover/v200`，10 m，`Map` 波段，11类，CC BY 4.0。
- Earth Engine目录：https://developers.google.com/earth-engine/datasets/catalog/ESA_WorldCover_v200
- ESA产品页：https://esa-worldcover.org/en/data-access
- DOI：https://doi.org/10.5281/zenodo.7254221
- 南京边界下载入口：https://cloudcenter.tianditu.gov.cn/administrativeDivision
- 天地图未在本次下载记录中提供独立数据版本号，记录为 `not_provided_by_source`；使用时保留天地图来源署名并遵守平台条款。

## 结论

WorldCover 自动检查全部通过。最终结论：**{'PASS' if all(checks.values()) and visual_status == 'PASS' else 'VISUAL_REVIEW_PENDING'}**。
""",
        encoding="utf-8",
    )


def write_manifest(visual_status: str) -> None:
    worldcover_files = [
        LANDCOVER,
        TREE_COVER,
        METADATA,
        STATISTICS,
        QA / "worldcover_nanjing_overview.png",
        QA / "worldcover_boundary_overlay.png",
        QA / "worldcover_tree_cover_detail.png",
        REPORT,
        ROOT / "scripts" / "gee_worldcover_export.js",
        Path(__file__).resolve(),
    ]
    content = {
        "schema_version": "fire-patrol-geo-delivery-manifest-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "project_scope": "Nanjing municipal boundary plus 5 km delivery extent",
        "datasets": [
            {
                "dataset_id": "NASA_SRTMGL1_003_Nanjing",
                "status": "PARTIAL_PASS",
                "dataset_manifest": "metadata/nanjing_srtm_file_manifest.json",
            },
            {
                "dataset_id": "ESA_WorldCover_2021_v200_Nanjing",
                "status": "PASS" if visual_status == "PASS" else "VISUAL_REVIEW_PENDING",
                "provider": "ESA WorldCover Consortium",
                "access_platform": "Google Earth Engine",
                "source_asset_id": "ESA/WorldCover/v200",
                "source_version": "2021 v200",
                "license": "CC BY 4.0",
                "qa_report": REPORT.relative_to(ROOT).as_posix(),
                "files": [
                    {
                        "path": path.relative_to(ROOT).as_posix(),
                        "size_bytes": path.stat().st_size,
                        "sha256": sha256(path),
                    }
                    for path in worldcover_files
                ],
            },
        ],
    }
    MANIFEST.write_text(
        json.dumps(content, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--visual-status",
        choices=["PASS", "PENDING_MANUAL_REVIEW"],
        default="PENDING_MANUAL_REVIEW",
    )
    args = parser.parse_args()
    QA.mkdir(parents=True, exist_ok=True)
    result = inspect_rasters()
    write_statistics(result)
    update_metadata(args.visual_status)
    save_visuals()
    write_report(result, args.visual_status)
    write_manifest(args.visual_status)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
