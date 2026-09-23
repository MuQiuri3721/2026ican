#!/usr/bin/env python3
"""Finalize QA, hashes, and manifest from existing Nanjing OSM GeoJSON files."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd

from process_nanjing_osm import (
    OSM_LICENSE,
    SOURCE_DATE,
    SOURCE_URL,
    create_qa_figure,
    load_delivery_mask,
    sha256,
)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / "data/nanjing/osm"
    boundary_path = root / "data/nanjing/srtm/nanjing_srtm_boundaries.geojson"
    pbf_path = root / "raw/osm/jiangsu-260920.osm.pbf"
    gpkg_path = root / "raw/osm/jiangsu-260920-free.gpkg/jiangsu.gpkg"
    paths = {
        "roads": output / "roads.geojson",
        "road_nodes": output / "road_nodes.geojson",
        "water_bodies": output / "water_bodies.geojson",
        "water_candidates": output / "water_candidates.geojson",
        "facilities": output / "facilities.geojson",
        "coverage_gaps": output / "coverage_gaps.json",
        "metadata": output / "nanjing_osm_metadata.csv",
        "qa_report": output / "nanjing_osm_qa_report.md",
        "qa_overlay": output / "nanjing_osm_qa_overlay.png",
        "manifest": output / "manifest.json",
    }
    for role in ("roads", "road_nodes", "water_bodies", "water_candidates", "facilities"):
        if not paths[role].exists():
            raise FileNotFoundError(paths[role])

    print("[1/4] Reading generated spatial outputs")
    roads = gpd.read_file(paths["roads"])
    road_nodes = gpd.read_file(paths["road_nodes"])
    water = gpd.read_file(paths["water_bodies"])
    water_candidates = gpd.read_file(paths["water_candidates"])
    facilities = gpd.read_file(paths["facilities"])
    mask = load_delivery_mask(boundary_path)

    print("[2/4] Running structural QA")
    road_node_ids = set(road_nodes["node_id"].astype(str))
    missing_refs = (set(roads["from_id"].astype(str)) | set(roads["to_id"].astype(str))) - road_node_ids
    invalid_road_geometries = int((~roads.geometry.is_valid | roads.geometry.is_empty).sum())
    invalid_water_geometries = int((~water.geometry.is_valid | water.geometry.is_empty).sum())
    nonpositive_lengths = int((roads["length_m"] <= 0).sum())
    candidate_links = set(water_candidates["water_id"].astype(str)) - set(water["water_id"].astype(str))
    qa_pass = not (
        missing_refs
        or invalid_road_geometries
        or invalid_water_geometries
        or nonpositive_lengths
        or candidate_links
    )
    qa_status = "PASS" if qa_pass else "FAIL"

    print("[3/4] Creating overlay and QA report")
    overlay_created = create_qa_figure(mask, roads, water, facilities, paths["qa_overlay"])
    highway_counts = Counter(roads["highway"].fillna("unknown"))
    lines = [
        "# Nanjing OSM delivery QA report",
        "",
        f"- Generated at: `{datetime.now(timezone.utc).replace(microsecond=0).isoformat()}`",
        "- Processing extent: Nanjing administrative boundary plus 5 km",
        f"- QA status: **{qa_status}**",
        f"- Road edges: {len(roads):,}",
        f"- Road nodes: {len(road_nodes):,}",
        f"- Water geometries: {len(water):,}",
        f"- Water candidates: {len(water_candidates):,}",
        f"- Facility candidates: {len(facilities):,}",
        f"- Missing road-node references: {len(missing_refs):,}",
        f"- Missing water-candidate parent links: {len(candidate_links):,}",
        f"- Invalid or empty road geometries: {invalid_road_geometries:,}",
        f"- Invalid or empty water geometries: {invalid_water_geometries:,}",
        f"- Non-positive road lengths: {nonpositive_lengths:,}",
        f"- Overlay image created: {overlay_created}",
        "",
        "## Top road classes",
        "",
    ]
    lines.extend(f"- `{key}`: {value:,}" for key, value in highway_counts.most_common(20))
    lines.extend(
        [
            "",
            "## Interpretation limits",
            "",
            "Road connectivity follows shared OSM node IDs. Grade-separated crossings are not connected unless the source data shares a node. This is a reproducible candidate graph, not production-grade evacuation navigation.",
            "",
            "Water and facility records are candidates. Unverified and null capability fields must not be promoted to usable or available without external evidence or field verification.",
            "",
        ]
    )
    paths["qa_report"].write_text("\n".join(lines), encoding="utf-8")

    print("[4/4] Hashing files and writing manifest")
    output_entries = []
    for role, path in paths.items():
        if role == "manifest" or not path.exists():
            continue
        output_entries.append(
            {"role": role, "path": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)}
        )
    manifest = {
        "delivery_id": "nanjing-osm-20260920",
        "region_id": "nanjing",
        "extent": "Nanjing administrative boundary plus 5 km",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "qa_status": qa_status,
        "source": {
            "provider": "Geofabrik / OpenStreetMap contributors",
            "url": SOURCE_URL,
            "source_date": SOURCE_DATE,
            "license": OSM_LICENSE,
            "pbf": {
                "path": str(pbf_path.relative_to(root)),
                "bytes": pbf_path.stat().st_size,
                "sha256": sha256(pbf_path),
            },
            "gpkg": {
                "path": str(gpkg_path.relative_to(root)),
                "bytes": gpkg_path.stat().st_size,
                "sha256": sha256(gpkg_path),
            },
            "boundary": {
                "path": str(boundary_path.relative_to(root)),
                "bytes": boundary_path.stat().st_size,
                "sha256": sha256(boundary_path),
            },
        },
        "outputs": output_entries,
    }
    paths["manifest"].write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "qa_status": qa_status,
        "counts": {
            "roads": len(roads),
            "road_nodes": len(road_nodes),
            "water": len(water),
            "water_candidates": len(water_candidates),
            "facilities": len(facilities),
        },
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
