#!/usr/bin/env python3
"""Build separate full, platform and public distribution manifests."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
ROOT_MANIFESTS = {
    "manifest.json",
    "manifest_full.json",
    "manifest_platform.json",
    "manifest_public.json",
}
PLANNING_INTERMEDIATE_PREFIXES = (
    "data/nanjing/planning_regions/raw/",
    "data/nanjing/planning_regions/rebuilt/",
)
PUBLIC_EXACT_EXCLUSIONS = {
    "data/nanjing/osm/roads.geojson",
    "data/nanjing/osm/road_nodes.geojson",
    "data/nanjing/osm/manifest.json",
    "data/nanjing/srtm/nanjing_srtm_boundaries.geojson",
    "data/overview/areas.geojson",
    "data/overview/manifest.json",
    "metadata/nanjing_srtm_file_manifest.json",
    "scripts/江苏省_省.geojson",
    "scripts/江苏省_市.geojson",
    "scripts/南京市_市.geojson",
}


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def all_files() -> list[Path]:
    files = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        parts = path.relative_to(ROOT).parts
        if ".git" in parts or "__pycache__" in parts or path.suffix == ".pyc":
            continue
        if path.parent == ROOT and path.name in ROOT_MANIFESTS:
            continue
        files.append(path)
    return files


def is_restricted_boundary(path: str) -> bool:
    if path.startswith("scripts/jiangsu_province_boundary_wgs84."):
        return True
    if path.startswith("scripts/jiangsu_prefecture_boundaries_wgs84."):
        return True
    if path.startswith("scripts/nanjing_boundary_wgs84."):
        return True
    return False


def include_full(path: str) -> bool:
    return True


def include_platform(path: str) -> bool:
    if path.startswith("raw/") or path.startswith("scripts/"):
        return False
    if path.startswith(PLANNING_INTERMEDIATE_PREFIXES):
        return False
    return (
        path.startswith("data/")
        or path.startswith("metadata/")
        or path.startswith("qa/")
        or path in {"README.md", "TEAM_DATA_DELIVERY.md", "THIRD_PARTY_DATA.md"}
    )


def include_public(path: str) -> bool:
    if path.startswith("raw/"):
        return False
    if path.startswith(PLANNING_INTERMEDIATE_PREFIXES):
        return False
    if path in PUBLIC_EXACT_EXCLUSIONS:
        return False
    if is_restricted_boundary(path):
        return False
    return True


def role_for(path: str) -> str:
    if path.startswith("data/"):
        return "delivery_data"
    if path.startswith("metadata/"):
        return "metadata"
    if path.startswith("qa/"):
        return "quality_assurance"
    if path.startswith("scripts/"):
        return "processing_or_reproduction"
    if path.startswith("raw/"):
        return "production_input"
    return "documentation_or_policy"


def records(paths: list[Path], predicate: Callable[[str], bool]) -> list[dict]:
    result = []
    for path in paths:
        rel = relative(path)
        if not predicate(rel):
            continue
        result.append({
            "path": rel,
            "role": role_for(rel),
            "size_bytes": path.stat().st_size,
            "sha256": sha256(path),
        })
    return result


def build_manifest(
    *,
    manifest_id: str,
    distribution_scope: str,
    description: str,
    entries: list[dict],
    entry_points: dict,
    exclusions: list[str],
) -> dict:
    counts = Counter(entry["role"] for entry in entries)
    return {
        "schema_version": "fire-patrol-distribution-manifest-v1",
        "manifest_id": manifest_id,
        "release_version": "v1.1-20260923",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "distribution_scope": distribution_scope,
        "description": description,
        "status": "PASS",
        "hash_algorithm": "SHA256",
        "file_count": len(entries),
        "total_size_bytes": sum(entry["size_bytes"] for entry in entries),
        "role_counts": dict(sorted(counts.items())),
        "entry_points": entry_points,
        "exclusion_policy": exclusions,
        "files": entries,
    }


def main() -> None:
    paths = all_files()
    full_entries = records(paths, include_full)
    platform_entries = records(paths, include_platform)
    public_entries = records(paths, include_public)

    manifests = {
        "manifest_full.json": build_manifest(
            manifest_id="geo-delivery-v2-full-team-archive",
            distribution_scope="internal_team_complete_archive",
            description=(
                "Complete local archive for production, QA and reproducibility. "
                "Contains raw inputs and restricted administrative geometries; do not publish as a whole."
            ),
            entries=full_entries,
            entry_points={
                "complete_area_index": "data/overview/areas.geojson",
                "data_root": "data",
                "root_dataset_manifest": "manifest.json",
            },
            exclusions=["root manifests themselves", "Git metadata", "Python cache files"],
        ),
        "manifest_platform.json": build_manifest(
            manifest_id="geo-delivery-v2-platform-data-package",
            distribution_scope="internal_team_platform_runtime",
            description=(
                "Internal package for platform integration. Includes formal data, metadata and QA, "
                "but excludes production raw downloads, processing scripts and planning intermediates."
            ),
            entries=platform_entries,
            entry_points={
                "data_root": "data",
                "complete_area_index": "data/overview/areas.geojson",
                "osm_roads": "data/nanjing/osm/roads.geojson",
                "osm_road_nodes": "data/nanjing/osm/road_nodes.geojson",
                "weather": "data/nanjing/weather",
            },
            exclusions=[
                "raw production inputs under raw/",
                "processing scripts",
                "planning_regions/raw and planning_regions/rebuilt",
                "Git metadata and Python cache files",
            ],
        ),
        "manifest_public.json": build_manifest(
            manifest_id="geo-delivery-v2-public-github",
            distribution_scope="public_github_repository",
            description=(
                "Public repository inventory containing code, documentation, QA, metadata and permitted "
                "lightweight outputs. Restricted Tianditu geometries and oversized OSM files are excluded."
            ),
            entries=public_entries,
            entry_points={
                "public_area_index": "data/overview/areas_public.geojson",
                "readme": "README.md",
                "third_party_policy": "THIRD_PARTY_DATA.md",
            },
            exclusions=[
                "Tianditu-derived raw or reconstructable administrative geometries",
                "raw OSM downloads",
                "roads.geojson and road_nodes.geojson",
                "local-only manifests that reference excluded files",
                "planning intermediate directories",
                "Git metadata and Python cache files",
            ],
        ),
    }

    for name, manifest in manifests.items():
        (ROOT / name).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    print(json.dumps({
        name: {
            "status": manifest["status"],
            "file_count": manifest["file_count"],
            "total_size_bytes": manifest["total_size_bytes"],
        }
        for name, manifest in manifests.items()
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
