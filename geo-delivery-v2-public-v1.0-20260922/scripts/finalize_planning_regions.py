"""Validate and package the four planning-display region boundaries.

Run after downloading planning_regions_overview.geojson from Google Earth Engine.
The script writes the normalized GeoJSON, metadata CSV, QA report, QA map and
manifest into data/nanjing/planning_regions by default.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
from shapely.validation import explain_validity


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


EXPECTED_IDS = {
    "planning_yuntai",
    "planning_ningzhen_east",
    "planning_yili",
    "planning_taihu_hills",
}

REQUIRED_FIELDS = {
    "region_id",
    "region_name_zh",
    "boundary_type",
    "source_basis",
    "source_url",
    "derivation_method",
    "planning_display_only",
    "official_boundary",
    "verification_status",
    "qa_status",
}

COLORS = {
    "planning_yuntai": "#e41a1c",
    "planning_ningzhen_east": "#377eb8",
    "planning_yili": "#4daf4a",
    "planning_taihu_hills": "#984ea3",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def parse_args() -> argparse.Namespace:
    base = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument(
        "--core-input",
        type=Path,
        help="GEE导出的 planning_regions_forest_terrain_core.geojson",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=base / "data" / "nanjing" / "planning_regions",
    )
    parser.add_argument(
        "--province-boundary",
        type=Path,
        default=base / "scripts" / "jiangsu_province_boundary_wgs84.geojson",
    )
    parser.add_argument(
        "--prefecture-boundaries",
        type=Path,
        default=base / "scripts" / "jiangsu_prefecture_boundaries_wgs84.geojson",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    regions = gpd.read_file(args.input)
    cores = gpd.read_file(args.core_input) if args.core_input else None
    province = gpd.read_file(args.province_boundary).to_crs("EPSG:4326")
    prefectures = gpd.read_file(args.prefecture_boundaries).to_crs("EPSG:4326")

    if regions.crs is None:
        regions = regions.set_crs("EPSG:4326")
    else:
        regions = regions.to_crs("EPSG:4326")
    if cores is not None:
        if cores.crs is None:
            cores = cores.set_crs("EPSG:4326")
        else:
            cores = cores.to_crs("EPSG:4326")

    errors: list[str] = []
    warnings: list[str] = []

    missing_fields = sorted(REQUIRED_FIELDS - set(regions.columns))
    if missing_fields:
        errors.append("缺少字段：" + ", ".join(missing_fields))

    ids = set(regions.get("region_id", []))
    if ids != EXPECTED_IDS:
        errors.append(
            "region_id 不完整：期望 "
            + ", ".join(sorted(EXPECTED_IDS))
            + "；实际 "
            + ", ".join(sorted(str(item) for item in ids))
        )
    if len(regions) != 4:
        errors.append(f"区域数量应为4，实际为{len(regions)}")

    if cores is None:
        warnings.append("未提供林地—丘陵核心层，仅检查规划外轮廓")
    else:
        core_ids = set(cores.get("region_id", []))
        if core_ids != EXPECTED_IDS:
            errors.append("核心层 region_id 不完整")
        if len(cores) != 4:
            errors.append(f"核心层区域数量应为4，实际为{len(cores)}")
        missing_core_fields = sorted(REQUIRED_FIELDS - set(cores.columns))
        if missing_core_fields:
            errors.append("核心层缺少字段：" + ", ".join(missing_core_fields))

    if regions.geometry.isna().any() or regions.geometry.is_empty.any():
        errors.append("存在空几何")
    if cores is not None and (cores.geometry.isna().any() or cores.geometry.is_empty.any()):
        errors.append("核心层存在空几何")

    invalid_rows = []
    for _, row in regions.iterrows():
        if row.geometry is not None and not row.geometry.is_valid:
            invalid_rows.append(
                f"{row.get('region_id', 'unknown')}: {explain_validity(row.geometry)}"
            )
    if invalid_rows:
        errors.append("存在无效几何：" + "; ".join(invalid_rows))
    if cores is not None:
        invalid_cores = []
        for _, row in cores.iterrows():
            if row.geometry is not None and not row.geometry.is_valid:
                invalid_cores.append(
                    f"{row.get('region_id', 'unknown')}: {explain_validity(row.geometry)}"
                )
        if invalid_cores:
            errors.append("核心层存在无效几何：" + "; ".join(invalid_cores))

    province_union = province.geometry.union_all()
    outside_area = regions.to_crs("EPSG:6933").geometry.difference(
        gpd.GeoSeries([province_union], crs="EPSG:4326").to_crs("EPSG:6933").iloc[0]
    ).area.sum()
    if outside_area > 100_000:
        errors.append(f"江苏省界外面积超过容差：{outside_area / 1e6:.3f} km²")

    if "planning_display_only" in regions.columns:
        bad = ~regions["planning_display_only"].map(bool_value)
        if bad.any():
            errors.append("planning_display_only 必须全部为 true")
    if "official_boundary" in regions.columns:
        unexpected = regions["official_boundary"].map(bool_value)
        if unexpected.any():
            errors.append("派生成果不得标记为 official_boundary=true")

    projected = regions.to_crs("EPSG:6933")
    regions["area_km2"] = projected.area / 1e6
    regions["centroid_lon"] = projected.centroid.to_crs("EPSG:4326").x
    regions["centroid_lat"] = projected.centroid.to_crs("EPSG:4326").y

    core_stats: dict[str, tuple[float, float]] = {}
    if cores is not None:
        cores_projected = cores.to_crs("EPSG:6933")
        cores["area_km2"] = cores_projected.area / 1e6
        outline_by_id = projected.set_index(regions["region_id"])
        core_by_id = cores_projected.set_index(cores["region_id"])
        for region_id in sorted(EXPECTED_IDS):
            outline_geometry = outline_by_id.loc[region_id, "geometry"]
            core_geometry = core_by_id.loc[region_id, "geometry"]
            outside_core_km2 = core_geometry.difference(outline_geometry).area / 1e6
            if outside_core_km2 > 0.01:
                errors.append(
                    f"{region_id} 核心层超出规划外轮廓 {outside_core_km2:.3f} km²"
                )
            outline_area = outline_geometry.area / 1e6
            core_area = core_geometry.area / 1e6
            ratio = core_area / outline_area * 100 if outline_area else 0
            core_stats[region_id] = (core_area, ratio)

    # 云台山与其余区域地理上分离；太湖与宜溧已在 GEE 中显式去重。
    overlap_rows = []
    for i in range(len(projected)):
        for j in range(i + 1, len(projected)):
            overlap = projected.geometry.iloc[i].intersection(
                projected.geometry.iloc[j]
            ).area / 1e6
            if overlap > 0.01:
                overlap_rows.append(
                    f"{regions.iloc[i]['region_id']} × "
                    f"{regions.iloc[j]['region_id']}: {overlap:.3f} km²"
                )
    if overlap_rows:
        errors.append("规划区存在面积重叠：" + "; ".join(overlap_rows))

    if (regions["area_km2"] <= 0).any():
        errors.append("存在面积为零的区域")

    qa_status = "PASS" if not errors else "FAIL"
    regions["qa_status"] = qa_status
    regions["qa_checked_at_utc"] = datetime.now(timezone.utc).isoformat()

    output_geojson = output_dir / "planning_regions_overview.geojson"
    regions.to_file(output_geojson, driver="GeoJSON", encoding="UTF-8")
    core_output_geojson = None
    if cores is not None:
        cores["qa_status"] = qa_status
        cores["qa_checked_at_utc"] = regions["qa_checked_at_utc"].iloc[0]
        core_output_geojson = output_dir / "planning_regions_forest_terrain_core.geojson"
        cores.to_file(core_output_geojson, driver="GeoJSON", encoding="UTF-8")

    metadata_path = output_dir / "planning_regions_metadata.csv"
    metadata_fields = [column for column in regions.columns if column != "geometry"]
    with metadata_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=metadata_fields)
        writer.writeheader()
        for _, row in regions.drop(columns="geometry").iterrows():
            writer.writerow({field: row[field] for field in metadata_fields})

    map_path = output_dir / "planning_regions_qa_map.png"
    fig, ax = plt.subplots(figsize=(10, 10), dpi=180)
    province.boundary.plot(ax=ax, color="#222222", linewidth=1.0)
    prefectures.boundary.plot(ax=ax, color="#bbbbbb", linewidth=0.45)
    for _, row in regions.iterrows():
        one = gpd.GeoDataFrame([row], geometry="geometry", crs="EPSG:4326")
        color = COLORS.get(row["region_id"], "#ff7f00")
        one.plot(ax=ax, facecolor=color, edgecolor=color, alpha=0.35, linewidth=1.2)
        if cores is not None:
            core_row = cores.loc[cores["region_id"] == row["region_id"]]
            core_row.plot(
                ax=ax,
                facecolor=color,
                edgecolor=color,
                alpha=0.75,
                linewidth=0.7,
            )
        ax.annotate(
            row["region_name_zh"],
            (row["centroid_lon"], row["centroid_lat"]),
            ha="center",
            va="center",
            fontsize=8,
            color="#111111",
        )
    ax.set_title("Four planning-display regions — spatial QA")
    ax.set_xlabel("Longitude (WGS84)")
    ax.set_ylabel("Latitude (WGS84)")
    ax.set_aspect("equal")
    fig.tight_layout()
    fig.savefig(map_path, bbox_inches="tight")
    plt.close(fig)

    report_path = output_dir / "planning_regions_qa_report.md"
    lines = [
        "# 4个规划展示区边界 QA 报告",
        "",
        f"- QA状态：**{qa_status}**",
        f"- 检查时间（UTC）：{regions['qa_checked_at_utc'].iloc[0]}",
        "- 成果坐标系：EPSG:4326",
        "- 用途限制：仅用于规划展示和区域索引，不是法定边界或执行调度区。",
        "",
        "## 区域统计",
        "",
        "| region_id | 名称 | 外轮廓面积（km²） | 核心面积（km²） | 核心覆盖率 | 边界类型 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for _, row in regions.sort_values("region_id").iterrows():
        core_area, core_ratio = core_stats.get(row["region_id"], (float("nan"), float("nan")))
        lines.append(
            f"| {row['region_id']} | {row['region_name_zh']} | "
            f"{row['area_km2']:.3f} | {core_area:.3f} | {core_ratio:.2f}% | "
            f"{row['boundary_type']} |"
        )
    lines.extend(["", "## 自动检查", ""])
    if errors:
        lines.extend(f"- ❌ {item}" for item in errors)
    else:
        passed_checks = [
            "- ✅ 区域数量和 region_id 完整",
            "- ✅ 必填来源与用途限制字段完整",
            "- ✅ 几何非空且有效",
            "- ✅ 成果位于江苏省界内",
            "- ✅ 四个规划展示区之间无显著重叠",
            "- ✅ 所有区域均标记为非官方、仅规划展示",
        ]
        if cores is not None:
            passed_checks.insert(
                -1, "- ✅ 林地—丘陵核心层位于对应规划外轮廓内"
            )
        lines.extend(passed_checks)
    if warnings:
        lines.extend(["", "## 警告", ""])
        lines.extend(f"- ⚠️ {item}" for item in warnings)
    lines.extend(
        [
            "",
            "## 仍需人工确认",
            "",
            "- 云台山派生范围与连云港市政府公布的保护界线图视觉位置是否一致；",
            "- 宁镇丘陵东段是否覆盖目标山体而未明显纳入平原；",
            "- 宜溧山地是否覆盖宜兴南部与溧阳南部连续山地；",
            "- 环太湖丘陵是否排除了宜溧片区，且未将太湖水体纳入。",
        ]
    )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    manifest_path = output_dir / "manifest.json"
    files = [output_geojson, metadata_path, map_path, report_path]
    if core_output_geojson is not None:
        files.append(core_output_geojson)
    rebuild_stats_source = args.input.parent / "planning_regions_rebuild_statistics.json"
    if rebuild_stats_source.exists():
        rebuild_stats_output = output_dir / rebuild_stats_source.name
        if rebuild_stats_source.resolve() != rebuild_stats_output.resolve():
            shutil.copy2(rebuild_stats_source, rebuild_stats_output)
        files.append(rebuild_stats_output)
    manifest = {
        "dataset_id": "jiangsu_planning_regions_overview_v1",
        "qa_status": qa_status,
        "planning_display_only": True,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "files": [
            {
                "path": file.name,
                "size_bytes": file.stat().st_size,
                "sha256": sha256(file),
            }
            for file in files
        ],
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"QA_STATUS={qa_status}")
    print(f"OUTPUT_DIR={output_dir}")
    for _, row in regions.sort_values("region_id").iterrows():
        print(f"{row['region_id']}={row['area_km2']:.3f} km2")
    if errors:
        for item in errors:
            print(f"ERROR={item}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
