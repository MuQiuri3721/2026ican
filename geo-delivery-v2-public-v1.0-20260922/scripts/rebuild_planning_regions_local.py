"""Locally rebuild smoother planning-region outlines from the GEE core layer.

The raw GEE files are never modified. Outputs are written to a separate
``rebuilt`` directory and remain project-defined planning-display boundaries.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
from shapely import make_valid
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union


AREA_CRS = "EPSG:6933"
DELIVERY_CRS = "EPSG:4326"
MIN_COMPONENT_AREA_M2 = 3_000_000
MAX_FILLED_HOLE_AREA_M2 = 3_000_000
CLOSING_RADIUS_M = 500
SIMPLIFY_TOLERANCE_M = 100


def parse_args() -> argparse.Namespace:
    base = Path(__file__).resolve().parents[1]
    data_dir = base / "data" / "nanjing" / "planning_regions"
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--core-input",
        type=Path,
        default=data_dir / "raw" / "planning_regions_forest_terrain_core.geojson",
    )
    parser.add_argument(
        "--outline-constraint",
        type=Path,
        default=data_dir / "raw" / "planning_regions_overview.geojson",
    )
    parser.add_argument(
        "--province-boundary",
        type=Path,
        default=base / "scripts" / "jiangsu_province_boundary_wgs84.geojson",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=data_dir / "rebuilt",
    )
    return parser.parse_args()


def polygon_parts(geometry) -> list[Polygon]:
    parts: list[Polygon] = []
    stack = [geometry]
    while stack:
        item = stack.pop()
        if item is None or item.is_empty:
            continue
        if item.geom_type == "Polygon":
            parts.append(item)
        elif hasattr(item, "geoms"):
            stack.extend(item.geoms)
    return parts


def polygonal_union(geometry, minimum_area_m2: float = 0) -> Polygon | MultiPolygon:
    parts = [
        polygon
        for polygon in polygon_parts(make_valid(geometry))
        if polygon.area >= minimum_area_m2
    ]
    if not parts:
        return Polygon()
    return make_valid(unary_union(parts))


def fill_small_holes(geometry, maximum_hole_area_m2: float):
    rebuilt = []
    for polygon in polygon_parts(make_valid(geometry)):
        retained_holes = []
        for ring in polygon.interiors:
            if Polygon(ring).area > maximum_hole_area_m2:
                retained_holes.append(ring.coords)
        rebuilt.append(Polygon(polygon.exterior.coords, retained_holes))
    return make_valid(unary_union(rebuilt)) if rebuilt else Polygon()


def describe(geometry) -> dict[str, float | int]:
    parts = polygon_parts(geometry)
    areas = sorted((part.area for part in parts), reverse=True)
    holes = [Polygon(ring).area for part in parts for ring in part.interiors]
    total = sum(areas)
    return {
        "area_km2": total / 1e6,
        "polygon_parts": len(parts),
        "holes": len(holes),
        "largest_component_percent": (areas[0] / total * 100) if total else 0,
        "components_under_3_km2": sum(area < MIN_COMPONENT_AREA_M2 for area in areas),
        "holes_under_3_km2": sum(area <= MAX_FILLED_HOLE_AREA_M2 for area in holes),
    }


def rebuild_outline(core_geometry, constraint_geometry, province_geometry):
    geometry = polygonal_union(core_geometry, MIN_COMPONENT_AREA_M2)
    geometry = fill_small_holes(geometry, MAX_FILLED_HOLE_AREA_M2)

    # Vector closing: bridge gaps narrower than about 1 km without the broad
    # 2 km GEE expansion that caused the previous outlines to absorb plains.
    geometry = geometry.buffer(CLOSING_RADIUS_M).buffer(-CLOSING_RADIUS_M)
    geometry = make_valid(geometry.intersection(constraint_geometry))
    geometry = make_valid(geometry.intersection(province_geometry))
    geometry = polygonal_union(geometry, MIN_COMPONENT_AREA_M2)
    geometry = fill_small_holes(geometry, MAX_FILLED_HOLE_AREA_M2)
    geometry = make_valid(geometry.simplify(SIMPLIFY_TOLERANCE_M, preserve_topology=True))
    return polygonal_union(geometry, MIN_COMPONENT_AREA_M2)


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    cores = gpd.read_file(args.core_input).to_crs(AREA_CRS)
    constraints = gpd.read_file(args.outline_constraint).to_crs(AREA_CRS)
    province = gpd.read_file(args.province_boundary).to_crs(AREA_CRS)
    province_geometry = make_valid(province.geometry.union_all())

    if set(cores["region_id"]) != set(constraints["region_id"]):
        raise ValueError("核心层与外轮廓约束层的 region_id 不一致")

    constraint_by_id = constraints.set_index("region_id")
    rebuilt_rows = []
    repaired_core_rows = []
    statistics = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "parameters": {
            "area_crs": AREA_CRS,
            "minimum_component_area_km2": MIN_COMPONENT_AREA_M2 / 1e6,
            "maximum_filled_hole_area_km2": MAX_FILLED_HOLE_AREA_M2 / 1e6,
            "closing_radius_m": CLOSING_RADIUS_M,
            "simplify_tolerance_m": SIMPLIFY_TOLERANCE_M,
        },
        "regions": {},
    }

    for _, row in cores.iterrows():
        region_id = row["region_id"]
        raw_core = make_valid(row.geometry)
        constraint = make_valid(constraint_by_id.loc[region_id, "geometry"])
        outline = rebuild_outline(raw_core, constraint, province_geometry)
        if outline.is_empty:
            raise ValueError(f"{region_id} 重建后为空")

        out_row = row.drop(labels="geometry").to_dict()
        out_row.update(
            {
                "layer_role": "planning_region_outline_local_rebuild",
                "boundary_type": "project_defined_overview_local_rebuild",
                "derivation_method": (
                    "repaired_core; remove_components_under_3km2; "
                    "fill_holes_under_3km2; 500m_vector_closing; "
                    "clip_to_GEE_outline_and_Jiangsu; simplify_100m"
                ),
                "local_minimum_component_area_km2": 3,
                "local_maximum_filled_hole_area_km2": 3,
                "local_closing_radius_m": CLOSING_RADIUS_M,
                "local_simplify_tolerance_m": SIMPLIFY_TOLERANCE_M,
                "qa_status": "PENDING_LOCAL_QA",
                "generated_at_utc": statistics["generated_at_utc"],
                "geometry": outline,
            }
        )
        rebuilt_rows.append(out_row)

        repaired_core = polygonal_union(raw_core.intersection(outline), 0)
        core_row = row.drop(labels="geometry").to_dict()
        core_row.update(
            {
                "layer_role": "forest_terrain_core_repaired",
                "qa_status": "PENDING_LOCAL_QA",
                "geometry": repaired_core,
            }
        )
        repaired_core_rows.append(core_row)

        statistics["regions"][region_id] = {
            "raw_core": describe(raw_core),
            "rebuilt_outline": describe(outline),
            "repaired_core": describe(repaired_core),
        }

    rebuilt = gpd.GeoDataFrame(rebuilt_rows, geometry="geometry", crs=AREA_CRS)
    repaired_cores = gpd.GeoDataFrame(
        repaired_core_rows, geometry="geometry", crs=AREA_CRS
    )

    # The project decision requires the Taihu region not to overlap Yili.
    yili_geometry = rebuilt.loc[
        rebuilt["region_id"] == "planning_yili", "geometry"
    ].iloc[0]
    taihu_index = rebuilt.index[rebuilt["region_id"] == "planning_taihu_hills"][0]
    rebuilt.at[taihu_index, "geometry"] = fill_small_holes(
        polygonal_union(
            rebuilt.at[taihu_index, "geometry"].difference(yili_geometry),
            MIN_COMPONENT_AREA_M2,
        ),
        MAX_FILLED_HOLE_AREA_M2,
    )
    taihu_outline = rebuilt.at[taihu_index, "geometry"]
    taihu_core_index = repaired_cores.index[
        repaired_cores["region_id"] == "planning_taihu_hills"
    ][0]
    repaired_cores.at[taihu_core_index, "geometry"] = polygonal_union(
        repaired_cores.at[taihu_core_index, "geometry"].intersection(taihu_outline),
        0,
    )

    # Refresh post-difference statistics for the Taihu region.
    statistics["regions"]["planning_taihu_hills"]["rebuilt_outline"] = describe(
        taihu_outline
    )
    statistics["regions"]["planning_taihu_hills"]["repaired_core"] = describe(
        repaired_cores.at[taihu_core_index, "geometry"]
    )

    outline_path = args.output_dir / "planning_regions_overview.geojson"
    core_path = args.output_dir / "planning_regions_forest_terrain_core.geojson"
    stats_path = args.output_dir / "planning_regions_rebuild_statistics.json"

    rebuilt.to_crs(DELIVERY_CRS).to_file(
        outline_path, driver="GeoJSON", encoding="UTF-8"
    )
    repaired_cores.to_crs(DELIVERY_CRS).to_file(
        core_path, driver="GeoJSON", encoding="UTF-8"
    )
    stats_path.write_text(
        json.dumps(statistics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"OUTLINE={outline_path}")
    print(f"CORE={core_path}")
    print(f"STATS={stats_path}")
    for region_id, values in statistics["regions"].items():
        before = values["raw_core"]
        after = values["rebuilt_outline"]
        print(
            f"{region_id}: {before['polygon_parts']} -> {after['polygon_parts']} parts; "
            f"{before['holes']} -> {after['holes']} holes; "
            f"{before['area_km2']:.3f} -> {after['area_km2']:.3f} km2"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
