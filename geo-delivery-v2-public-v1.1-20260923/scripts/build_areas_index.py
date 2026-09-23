#!/usr/bin/env python3
"""Build the unified Jiangsu/Nanjing/planning-region area index."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib import font_manager
from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform as shapely_transform, unary_union
from shapely.validation import explain_validity


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/overview"
TIANDITU_URL = "https://cloudcenter.tianditu.gov.cn/administrativeDivision"


def read_collection(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def feature(geometry, **properties) -> dict:
    return {
        "type": "Feature",
        "properties": properties,
        "geometry": mapping(geometry),
    }


def polygon_parts(geometry):
    return geometry.geoms if geometry.geom_type == "MultiPolygon" else [geometry]


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat()
    chinese_font = Path(r"C:\Windows\Fonts\msyh.ttc")
    if chinese_font.exists():
        font_manager.fontManager.addfont(str(chinese_font))
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(chinese_font)).get_name()
        plt.rcParams["axes.unicode_minus"] = False

    province_source = ROOT / "scripts/jiangsu_province_boundary_wgs84.geojson"
    prefecture_source = ROOT / "scripts/jiangsu_prefecture_boundaries_wgs84.geojson"
    nanjing_source = ROOT / "data/nanjing/srtm/nanjing_srtm_boundaries.geojson"
    planning_source = ROOT / "data/nanjing/planning_regions/planning_regions_overview.geojson"

    province_fc = read_collection(province_source)
    prefecture_fc = read_collection(prefecture_source)
    nanjing_fc = read_collection(nanjing_source)
    planning_fc = read_collection(planning_source)

    province_geometry = shape(province_fc["features"][0]["geometry"])
    prefectures = prefecture_fc["features"]
    nanjing_feature = next(
        item for item in nanjing_fc["features"]
        if item["properties"].get("boundary_type") == "confirmed_aoi"
    )
    nanjing_geometry = shape(nanjing_feature["geometry"])

    features = []
    features.append(feature(
        province_geometry,
        region_id="jiangsu",
        name="江苏省",
        name_zh="江苏省",
        region_level="province",
        scope_type="province_overview",
        parent_region_id=None,
        administrative_code="320000",
        source_provider="国家地理信息公共服务平台（天地图）",
        source_url=TIANDITU_URL,
        source_version="not_provided_by_source",
        source_crs="CGCS2000 / EPSG:4490",
        delivery_crs="EPSG:4326",
        acquired_at="2026-09-20",
        geometry_source="scripts/jiangsu_province_boundary_wgs84.geojson",
        boundary_semantics="administrative_division_boundary",
        official_boundary=False,
        boundary_authority_note="Administrative-division geometry downloaded from Tianditu; legal survey authority was not independently revalidated.",
        usage_restriction="该数据仅供地图可视化使用",
        redistribution_status="not_permitted_for_public_repository",
        public_geometry_distribution="excluded",
        planning_display_only=False,
        executable_dispatch_area=False,
        data_availability="overview_available",
        data_root="data/nanjing/jiangsu_tree_cover_overview",
        qa_status="PASS",
        display_order=1,
    ))

    for index, source_feature in enumerate(sorted(prefectures, key=lambda item: item["properties"]["gb"]), start=10):
        props = source_feature["properties"]
        code = str(props["gb"])[-6:]
        name = props["name"]
        geometry = shape(source_feature["geometry"])
        features.append(feature(
            geometry,
            region_id=f"prefecture_{code}",
            name=name,
            name_zh=name,
            region_level="prefecture",
            scope_type="prefecture_overview",
            parent_region_id="jiangsu",
            administrative_code=code,
            source_provider="国家地理信息公共服务平台（天地图）",
            source_url=TIANDITU_URL,
            source_version="not_provided_by_source",
            source_crs="CGCS2000 / EPSG:4490",
            delivery_crs="EPSG:4326",
            acquired_at="2026-09-20",
            geometry_source="scripts/jiangsu_prefecture_boundaries_wgs84.geojson",
            boundary_semantics="administrative_division_boundary",
            official_boundary=False,
            boundary_authority_note="Administrative-division geometry downloaded from Tianditu; legal survey authority was not independently revalidated.",
            usage_restriction="该数据仅供地图可视化使用",
            redistribution_status="not_permitted_for_public_repository",
            public_geometry_distribution="excluded",
            planning_display_only=False,
            executable_dispatch_area=False,
            data_availability="overview_available",
            data_root="data/nanjing/jiangsu_tree_cover_overview",
            qa_status="PASS",
            display_order=index,
        ))

    features.append(feature(
        nanjing_geometry,
        region_id="nanjing_delivery",
        name="南京市正式详细数据区",
        name_zh="南京市正式详细数据区",
        region_level="detailed_delivery_region",
        scope_type="detailed_delivery_region",
        parent_region_id="prefecture_320100",
        administrative_code="320100",
        source_provider="国家地理信息公共服务平台（天地图）",
        source_url=TIANDITU_URL,
        source_version="not_provided_by_source",
        source_crs="CGCS2000 / EPSG:4490",
        delivery_crs="EPSG:4326",
        acquired_at="2026-09-10",
        geometry_source="data/nanjing/srtm/nanjing_srtm_boundaries.geojson#confirmed_aoi",
        boundary_provenance_ref="metadata/nanjing_boundary_provenance.json",
        boundary_semantics="administrative_boundary_used_as_detailed_delivery_region",
        official_boundary=False,
        boundary_authority_note="Project delivery geometry derived from the Tianditu Nanjing administrative division; not a forest-management boundary.",
        usage_restriction="该数据仅供地图可视化使用",
        redistribution_status="not_permitted_for_public_repository",
        public_geometry_distribution="excluded",
        planning_display_only=False,
        executable_dispatch_area=False,
        data_availability="detailed_delivery_available",
        analysis_buffer_m=5000,
        analysis_buffer_note="Detailed rasters and OSM data extend to a separate 5 km technical buffer; this indexed polygon is the unbuffered Nanjing boundary.",
        data_root="data/nanjing",
        qa_status="PASS",
        display_order=30,
    ))

    for index, source_feature in enumerate(planning_fc["features"], start=40):
        props = source_feature["properties"]
        geometry = shape(source_feature["geometry"])
        features.append(feature(
            geometry,
            region_id=props["region_id"],
            name=props["region_name_zh"],
            name_zh=props["region_name_zh"],
            region_level="planning_display_region",
            scope_type="planning_display_region",
            parent_region_id="jiangsu",
            administrative_code=None,
            source_provider="Project-derived from NASA SRTM, ESA WorldCover and cited geographic descriptions",
            source_url=props.get("source_url"),
            source_version="local rebuild v1, 2026-09-21",
            source_crs="EPSG:4326",
            delivery_crs="EPSG:4326",
            acquired_at="2026-09-21",
            geometry_source="data/nanjing/planning_regions/planning_regions_overview.geojson",
            boundary_semantics="project_defined_overview_boundary",
            official_boundary=False,
            boundary_authority_note="Project-derived overview boundary; not a statutory natural-region, protected-area or dispatch boundary.",
            usage_restriction="project-derived planning display only",
            redistribution_status="included_with_nonofficial_boundary_notice",
            public_geometry_distribution="included",
            planning_display_only=True,
            executable_dispatch_area=False,
            verification_status=props.get("verification_status", "unverified"),
            data_availability="planning_overview_only",
            data_root="data/nanjing/planning_regions",
            qa_status=props.get("qa_status", "UNKNOWN"),
            display_order=index,
        ))

    required = {
        "region_id", "name", "name_zh", "region_level", "scope_type",
        "source_provider", "source_url", "source_version", "delivery_crs",
        "geometry_source", "boundary_semantics", "planning_display_only",
        "executable_dispatch_area", "data_availability", "qa_status",
    }
    ids = [item["properties"]["region_id"] for item in features]
    expected_prefecture_codes = {
        "320100", "320200", "320300", "320400", "320500", "320600", "320700",
        "320800", "320900", "321000", "321100", "321200", "321300",
    }
    actual_prefecture_codes = {
        item["properties"]["administrative_code"]
        for item in features if item["properties"]["region_level"] == "prefecture"
    }
    metric_transformer = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    project_metric = lambda x, y, z=None: metric_transformer.transform(x, y)
    province_metric = shapely_transform(project_metric, province_geometry)
    prefecture_metric = shapely_transform(
        project_metric,
        unary_union([shape(item["geometry"]) for item in prefectures]),
    )
    nanjing_prefecture_geometry = shape(next(
        item["geometry"] for item in prefectures if item["properties"]["name"] == "南京市"
    ))
    nanjing_prefecture_metric = shapely_transform(project_metric, nanjing_prefecture_geometry)
    nanjing_delivery_metric = shapely_transform(project_metric, nanjing_geometry)
    prefectures_outside_ratio = prefecture_metric.difference(province_metric).area / prefecture_metric.area
    province_uncovered_ratio = province_metric.difference(prefecture_metric).area / province_metric.area
    nanjing_symmetric_difference_ratio = (
        nanjing_prefecture_metric.symmetric_difference(nanjing_delivery_metric).area
        / nanjing_prefecture_metric.area
    )
    planning_outside_ratios = []
    for item in planning_fc["features"]:
        geometry_metric = shapely_transform(project_metric, shape(item["geometry"]))
        planning_outside_ratios.append(geometry_metric.difference(province_metric).area / geometry_metric.area)
    checks = {
        "feature_count_19": len(features) == 19,
        "unique_region_ids": len(ids) == len(set(ids)),
        "province_count_1": sum(item["properties"]["region_level"] == "province" for item in features) == 1,
        "prefecture_count_13": sum(item["properties"]["region_level"] == "prefecture" for item in features) == 13,
        "prefecture_codes_complete": actual_prefecture_codes == expected_prefecture_codes,
        "prefecture_union_matches_province": prefectures_outside_ratio < 1e-8 and province_uncovered_ratio < 1e-8,
        "detailed_delivery_count_1": sum(item["properties"]["region_level"] == "detailed_delivery_region" for item in features) == 1,
        "nanjing_delivery_matches_prefecture": nanjing_symmetric_difference_ratio < 1e-4,
        "planning_count_4": sum(item["properties"]["region_level"] == "planning_display_region" for item in features) == 4,
        "planning_regions_within_jiangsu_tolerance": max(planning_outside_ratios) < 1e-4,
        "required_properties_complete": all(required.issubset(item["properties"]) for item in features),
        "all_geometries_valid": all(shape(item["geometry"]).is_valid for item in features),
        "all_geometries_nonempty": all(not shape(item["geometry"]).is_empty for item in features),
        "all_delivery_crs_epsg4326": all(item["properties"]["delivery_crs"] == "EPSG:4326" for item in features),
        "planning_marked_nonofficial": all(
            not item["properties"]["official_boundary"] and item["properties"]["planning_display_only"]
            for item in features if item["properties"]["region_level"] == "planning_display_region"
        ),
        "nanjing_delivery_parent_correct": next(
            item for item in features if item["properties"]["region_id"] == "nanjing_delivery"
        )["properties"]["parent_region_id"] == "prefecture_320100",
    }

    for item in features:
        geometry = shape(item["geometry"])
        item["properties"]["geometry_type"] = geometry.geom_type
        item["properties"]["geometry_valid"] = geometry.is_valid
        item["properties"]["generated_at_utc"] = generated_at

    output_geojson = OUTPUT / "areas.geojson"
    collection = {
        "type": "FeatureCollection",
        "name": "fire_patrol_unified_area_index",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "features": features,
    }
    output_geojson.write_text(json.dumps(collection, ensure_ascii=False, indent=2), encoding="utf-8")

    public_features = []
    for item in features:
        if item["properties"]["region_level"] != "planning_display_region":
            continue
        public_item = json.loads(json.dumps(item, ensure_ascii=False))
        public_item["properties"]["distribution_scope"] = "public_repository"
        public_item["properties"]["administrative_context_geometry_included"] = False
        public_item["properties"]["usage_note"] = (
            "Project-derived planning-display geometry; not an official administrative, "
            "statutory planning, protected-area or executable dispatch boundary."
        )
        public_features.append(public_item)

    public_geojson = OUTPUT / "areas_public.geojson"
    public_collection = {
        "type": "FeatureCollection",
        "name": "fire_patrol_public_planning_area_index",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "public_distribution_note": (
            "This public index contains only the four project-derived planning-display regions. "
            "Tianditu-derived administrative and detailed-delivery geometries are intentionally excluded."
        ),
        "features": public_features,
    }
    public_geojson.write_text(
        json.dumps(public_collection, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    metadata_fields = [
        "region_id", "name_zh", "region_level", "scope_type", "parent_region_id",
        "administrative_code", "source_provider", "source_url", "source_version",
        "source_crs", "delivery_crs", "acquired_at", "geometry_source",
        "boundary_semantics", "official_boundary", "planning_display_only",
        "executable_dispatch_area", "verification_status", "data_availability",
        "usage_restriction", "redistribution_status", "public_geometry_distribution",
        "data_root", "qa_status", "display_order",
    ]
    metadata_csv = OUTPUT / "areas_metadata.csv"
    with metadata_csv.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=metadata_fields)
        writer.writeheader()
        for item in features:
            props = item["properties"]
            writer.writerow({key: props.get(key) for key in metadata_fields})

    map_path = OUTPUT / "areas_qa_map.png"
    fig, ax = plt.subplots(figsize=(10, 9), constrained_layout=True)
    for item in features:
        props = item["properties"]
        geometry = shape(item["geometry"])
        level = props["region_level"]
        if level == "province":
            style = {"color": "#1d4ed8", "linewidth": 2.0, "fill": False, "zorder": 1}
        elif level == "prefecture":
            style = {"color": "#94a3b8", "linewidth": 0.7, "fill": False, "zorder": 2}
        elif level == "detailed_delivery_region":
            style = {"color": "#dc2626", "linewidth": 2.0, "fill": False, "zorder": 4}
        else:
            style = {"color": "#16a34a", "linewidth": 1.0, "fill": True, "zorder": 3}
        for part in polygon_parts(geometry):
            x, y = part.exterior.xy
            if style["fill"]:
                ax.fill(x, y, color=style["color"], alpha=0.25, zorder=style["zorder"])
            ax.plot(x, y, color=style["color"], linewidth=style["linewidth"], zorder=style["zorder"])
        if level in {"detailed_delivery_region", "planning_display_region"}:
            point = geometry.representative_point()
            ax.annotate(
                props["name_zh"], (point.x, point.y), xytext=(4, 4),
                textcoords="offset points", fontsize=8,
                bbox={"facecolor": "white", "alpha": 0.75, "edgecolor": "none", "pad": 1},
                zorder=5,
            )
    ax.set_title("Unified area index QA: Jiangsu, 13 prefectures, Nanjing delivery and 4 planning regions")
    ax.set_xlabel("Longitude (EPSG:4326)")
    ax.set_ylabel("Latitude (EPSG:4326)")
    ax.set_aspect("equal", adjustable="box")
    fig.savefig(map_path, dpi=180)
    plt.close(fig)

    qa_status = "PASS" if all(checks.values()) else "FAIL"
    qa_report = OUTPUT / "areas_qa_report.md"
    rows = "\n".join(
        f"- {'PASS' if value else 'FAIL'} `{name}`"
        for name, value in checks.items()
    )
    qa_report.write_text(
        "# Unified areas.geojson QA report\n\n"
        f"- Generated at UTC: `{generated_at}`\n"
        f"- QA status: **{qa_status}**\n"
        f"- Feature count: {len(features)}\n"
        "- Composition: Jiangsu province 1, prefectures 13, Nanjing detailed delivery region 1, planning-display regions 4.\n\n"
        "## Checks\n\n"
        f"{rows}\n\n"
        "## Spatial consistency metrics\n\n"
        f"- Prefecture union outside province ratio: `{prefectures_outside_ratio:.12f}`\n"
        f"- Province area uncovered by prefecture union ratio: `{province_uncovered_ratio:.12f}`\n"
        f"- Nanjing delivery/prefecture symmetric-difference ratio: `{nanjing_symmetric_difference_ratio:.12f}`\n"
        f"- Maximum planning-region area outside Jiangsu ratio: `{max(planning_outside_ratios):.12f}`\n\n"
        "## Semantics\n\n"
        "Administrative, detailed-delivery and planning-display records are deliberately separate. "
        "The Nanjing detailed-delivery polygon is unbuffered; its 5 km technical processing extent remains in the module boundary file. "
        "The four planning regions are project-derived overview boundaries and cannot be presented as statutory or executable dispatch areas.\n",
        encoding="utf-8",
    )

    files = [output_geojson, public_geojson, metadata_csv, map_path, qa_report]
    manifest_path = OUTPUT / "manifest.json"
    manifest = {
        "schema_version": "fire-patrol-area-index-manifest-v1",
        "dataset_id": "Jiangsu_Nanjing_Unified_Area_Index_v1",
        "generated_at_utc": generated_at,
        "qa_status": qa_status,
        "feature_count": len(features),
        "public_feature_count": len(public_features),
        "public_distribution_policy": {
            "administrative_geometries": "excluded",
            "detailed_delivery_geometry": "excluded",
            "project_derived_planning_geometries": "included"
        },
        "crs": "EPSG:4326",
        "files": [
            {
                "path": path.name,
                "size_bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in files
        ],
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "output": str(output_geojson),
        "qa_status": qa_status,
        "feature_count": len(features),
        "checks": checks,
    }, ensure_ascii=False, indent=2))
    if qa_status != "PASS":
        invalid = [
            (item["properties"]["region_id"], explain_validity(shape(item["geometry"])))
            for item in features if not shape(item["geometry"]).is_valid
        ]
        if invalid:
            print(json.dumps({"invalid_geometries": invalid}, ensure_ascii=False, indent=2))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
