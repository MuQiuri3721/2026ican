#!/usr/bin/env python3
"""Build the root geo-delivery manifest from all present delivery artifacts."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EXCLUDED_PARTS = {"__pycache__", ".git"}
EXCLUDED_NAMES = {
    "manifest.json",
    "manifest_full.json",
    "manifest_platform.json",
    "manifest_public.json",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def normalized(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def file_record(path: Path, root: Path) -> dict[str, Any]:
    relative = normalized(path, root)
    top = relative.split("/", 1)[0]
    role = {
        "raw": "raw_source",
        "data": "delivery_data",
        "metadata": "metadata",
        "qa": "quality_assurance",
        "scripts": "processing_or_source_support",
    }.get(top, "documentation")
    return {
        "path": relative,
        "role": role,
        "size_bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def inventory(root: Path) -> list[dict[str, Any]]:
    records = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(root).parts
        if any(part in EXCLUDED_PARTS for part in relative_parts):
            continue
        if path.parent == root and path.name in EXCLUDED_NAMES:
            continue
        records.append(file_record(path, root))
    return records


def select(records: list[dict[str, Any]], *prefixes: str) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in record.items() if key != "role"}
        for record in records
        if any(record["path"].startswith(prefix) for prefix in prefixes)
    ]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    records = inventory(root)
    srtm_manifest_path = root / "metadata/nanjing_srtm_file_manifest.json"
    osm_manifest_path = root / "data/nanjing/osm/manifest.json"
    weather_manifest_path = root / "data/nanjing/weather/manifest.json"
    planning_manifest_path = root / "data/nanjing/planning_regions/manifest.json"
    areas_manifest_path = root / "data/overview/manifest.json"
    srtm = read_json(srtm_manifest_path)
    osm = read_json(osm_manifest_path)
    weather = read_json(weather_manifest_path)
    planning = read_json(planning_manifest_path)
    areas = read_json(areas_manifest_path)

    datasets = [
        {
            "dataset_id": "NASA_SRTMGL1_003_Nanjing",
            "status": srtm.get("qa_status", "UNKNOWN"),
            "provider": "NASA / USGS",
            "source_asset_id": "USGS/SRTMGL1_003",
            "dataset_manifest": normalized(srtm_manifest_path, root),
            "qa_report": "qa/nanjing_srtm_qa_report.md",
            "files": select(
                records,
                "data/nanjing/srtm/",
                "metadata/nanjing_srtm_",
                "metadata/srtm_product_metadata.json",
                "metadata/nanjing_boundary_provenance.json",
                "qa/nanjing_srtm_",
                "qa/srtm_",
                "scripts/gee_srtm_terrain_export.js",
                "scripts/finalize_srtm_fixed_checkpoints.py",
            ),
        },
        {
            "dataset_id": "ESA_WorldCover_2021_v200_Nanjing",
            "status": "PASS",
            "provider": "ESA WorldCover Consortium",
            "access_platform": "Google Earth Engine",
            "source_asset_id": "ESA/WorldCover/v200",
            "source_version": "2021 v200",
            "license": "CC BY 4.0",
            "qa_report": "qa/nanjing_worldcover_qa_report.md",
            "files": select(
                records,
                "data/nanjing/worldcover/",
                "qa/nanjing_worldcover_qa_report.md",
                "qa/worldcover_",
                "scripts/gee_worldcover_export.js",
            ),
        },
        {
            "dataset_id": "ESA_WorldCover_2021_v200_Jiangsu_Overview",
            "status": "PASS",
            "provider": "ESA WorldCover Consortium",
            "access_platform": "Google Earth Engine",
            "source_asset_id": "ESA/WorldCover/v200",
            "source_version": "2021 v200",
            "license": "CC BY 4.0",
            "qa_report": "qa/jiangsu_tree_cover_overview_qa_report.md",
            "files": select(
                records,
                "data/nanjing/jiangsu_tree_cover_overview/",
                "qa/jiangsu_tree_cover_overview_",
                "scripts/gee_jiangsu_tree_cover_overview_export.js",
            ),
        },
        {
            "dataset_id": "OpenStreetMap_Geofabrik_Jiangsu_20260920_Nanjing_Clip",
            "status": osm.get("qa_status", "UNKNOWN"),
            "provider": "Geofabrik / OpenStreetMap contributors",
            "source_version": "jiangsu-260920",
            "license": "ODbL 1.0",
            "dataset_manifest": normalized(osm_manifest_path, root),
            "qa_report": "data/nanjing/osm/nanjing_osm_qa_report.md",
            "files": select(
                records,
                "raw/osm/",
                "data/nanjing/osm/",
                "scripts/process_nanjing_osm.py",
                "scripts/finalize_nanjing_osm.py",
            ),
        },
        {
            "dataset_id": "Open_Meteo_Nanjing_Current_Forecast_Replay_20260921",
            "status": weather.get("qa_status", "UNKNOWN"),
            "provider": "Open-Meteo",
            "source_version": "API response fetched 2026-09-21",
            "license": "CC BY 4.0",
            "dataset_manifest": normalized(weather_manifest_path, root),
            "qa_report": "qa/nanjing_weather_qa_report.md",
            "files": select(
                records,
                "data/nanjing/weather/",
                "qa/nanjing_weather_qa_report.md",
                "scripts/fetch_nanjing_weather.py",
            ),
        },
        {
            "dataset_id": "Tianditu_Administrative_Boundaries_Nanjing_Jiangsu",
            "status": "PASS",
            "provider": "天地图",
            "source_url": "https://cloudcenter.tianditu.gov.cn/administrativeDivision",
            "source_version": "not_provided_by_source",
            "license": "subject_to_tianditu_terms",
            "standard_open_license": "not_provided_by_source",
            "attribution": "天地图",
            "provenance": "metadata/nanjing_boundary_provenance.json",
            "files": [
                {key: value for key, value in record.items() if key != "role"}
                for record in records
                if record["path"].startswith("scripts/")
                and (
                    "boundary_wgs84" in record["path"]
                    or "boundaries_wgs84" in record["path"]
                    or record["path"].endswith("江苏省_省.geojson")
                    or record["path"].endswith("江苏省_市.geojson")
                    or record["path"].endswith("南京市_市.geojson")
                )
            ],
        },
        {
            "dataset_id": "Jiangsu_Four_Planning_Display_Regions_v1",
            "status": planning.get("qa_status", "UNKNOWN"),
            "provider": "Project-derived from NASA SRTM, ESA WorldCover and authoritative geographic descriptions",
            "source_version": "local rebuild v1, 2026-09-21",
            "dataset_manifest": normalized(planning_manifest_path, root),
            "qa_report": "data/nanjing/planning_regions/planning_regions_qa_report.md",
            "usage_restriction": "planning display and regional indexing only; not official or executable dispatch boundaries",
            "files": select(
                records,
                "data/nanjing/planning_regions/",
                "scripts/gee_planning_regions_overview.js",
                "scripts/rebuild_planning_regions_local.py",
                "scripts/finalize_planning_regions.py",
            ),
        },
        {
            "dataset_id": "Jiangsu_Nanjing_Unified_Area_Index_v1",
            "status": areas.get("qa_status", "UNKNOWN"),
            "provider": "Tianditu administrative divisions plus project-defined planning overview boundaries",
            "source_version": "area index v1, generated 2026-09-22",
            "dataset_manifest": normalized(areas_manifest_path, root),
            "qa_report": "data/overview/areas_qa_report.md",
            "usage_restriction": "Administrative, detailed-delivery and planning-display geometries have distinct scope_type and boundary semantics.",
            "files": select(
                records,
                "data/overview/",
                "scripts/build_areas_index.py",
            ),
        },
    ]
    statuses = [dataset["status"] for dataset in datasets]
    overall_status = "PASS" if statuses and all(value == "PASS" for value in statuses) else "PARTIAL_PASS"
    manifest = {
        "schema_version": "fire-patrol-geo-delivery-manifest-v2",
        "manifest_role": "root summary and complete present-file inventory; dataset sub-manifests remain authoritative for module details",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "project_scope": "Nanjing detailed delivery plus Jiangsu provincial overview",
        "overall_status": overall_status,
        "inventory_policy": {
            "included": "all present files below geo-delivery-v2 except the root manifest itself and cache directories",
            "hash_algorithm": "SHA256",
            "file_count": len(records),
        },
        "datasets": datasets,
        "known_gaps": [
            "Weather values are model or reanalysis outputs and are not local-station observations.",
            "OSM facility and water-source candidates remain unverified unless external evidence is added.",
            "The four planning-display regions are project-derived overview boundaries, not statutory natural-region or protected-area boundaries.",
        ],
        "file_inventory": records,
    }
    output = root / "manifest.json"
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "manifest": str(output),
        "overall_status": overall_status,
        "dataset_count": len(datasets),
        "inventory_file_count": len(records),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
