#!/usr/bin/env python3
"""Build the Nanjing OSM delivery package from the Jiangsu Geofabrik extract.

The script intentionally uses the PBF for the road graph so that original OSM
node connectivity and tags are retained. The companion GeoPackage is used for
water geometries and source-classified facility candidates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import geopandas as gpd
import osmium
import pandas as pd
from pyproj import Transformer
from shapely.geometry import GeometryCollection, LineString, MultiLineString, Point
from shapely.ops import transform as transform_geometry
from shapely.prepared import prep


CRS_WGS84 = "EPSG:4326"
CRS_METRIC = "EPSG:32650"
SOURCE_DATE = "2026-09-20"
SOURCE_URL = "https://download.geofabrik.de/asia/china/jiangsu.html"
OSM_LICENSE = "Open Database License 1.0 (ODbL 1.0)"

FACILITY_CLASSES = {
    "fire_station",
    "police",
    "hospital",
    "clinic",
    "shelter",
    "parking",
    "tourist_info",
    "ranger_station",
    "helipad",
}

ROAD_TAGS = (
    "highway",
    "name",
    "ref",
    "oneway",
    "maxspeed",
    "access",
    "foot",
    "motor_vehicle",
    "vehicle",
    "bridge",
    "tunnel",
    "layer",
    "surface",
    "tracktype",
    "smoothness",
)


def parse_args() -> argparse.Namespace:
    here = Path(__file__).resolve()
    root = here.parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument(
        "--boundary",
        type=Path,
        default=root / "data/nanjing/srtm/nanjing_srtm_boundaries.geojson",
    )
    parser.add_argument(
        "--gpkg",
        type=Path,
        default=root / "raw/osm/jiangsu-260920-free.gpkg/jiangsu.gpkg",
    )
    parser.add_argument(
        "--pbf",
        type=Path,
        default=root / "raw/osm/jiangsu-260920.osm.pbf",
    )
    parser.add_argument("--output", type=Path, default=root / "data/nanjing/osm")
    return parser.parse_args()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def stable_clip_node_id(x: float, y: float) -> str:
    key = f"{x:.9f},{y:.9f}".encode("ascii")
    return "clip_" + hashlib.sha1(key).hexdigest()[:16]


def line_parts(geometry: Any) -> Iterable[LineString]:
    if geometry is None or geometry.is_empty:
        return
    if isinstance(geometry, LineString):
        yield geometry
    elif isinstance(geometry, MultiLineString):
        yield from geometry.geoms
    elif isinstance(geometry, GeometryCollection):
        for part in geometry.geoms:
            yield from line_parts(part)


def normalize_osm_id(value: Any) -> int | None:
    if value is None or pd.isna(value):
        return None
    try:
        return abs(int(str(value)))
    except (TypeError, ValueError):
        return None


def load_delivery_mask(boundary_path: Path):
    boundary = gpd.read_file(boundary_path).to_crs(CRS_WGS84)
    if "boundary_type" not in boundary.columns:
        raise ValueError("Boundary file has no boundary_type field")
    selected = boundary.loc[
        boundary["boundary_type"].eq("delivery_extent_aoi_plus_5km")
    ]
    if len(selected) != 1:
        raise ValueError(
            "Expected exactly one delivery_extent_aoi_plus_5km geometry, "
            f"found {len(selected)}"
        )
    mask = selected.geometry.iloc[0]
    if mask.is_empty or not mask.is_valid:
        raise ValueError("Delivery mask is empty or invalid")
    return mask


def read_and_clip(gpkg: Path, layer: str, mask) -> gpd.GeoDataFrame:
    frame = gpd.read_file(gpkg, layer=layer, mask=mask).to_crs(CRS_WGS84)
    if frame.empty:
        return frame
    return gpd.clip(frame, mask, keep_geom_type=False).explode(index_parts=False)


class OSMCollector(osmium.SimpleHandler):
    def __init__(self, mask, target_ids: set[int], road_way_ids: set[int]):
        super().__init__()
        self.mask = mask
        self.prepared_mask = prep(mask)
        self.target_ids = target_ids
        self.road_way_ids = road_way_ids
        self.tag_candidates: dict[int, list[tuple[str, dict[str, str]]]] = defaultdict(list)
        self.entrance_candidates: list[dict[str, Any]] = []
        self.edges: list[dict[str, Any]] = []
        self.edge_geometries: list[LineString] = []
        self.nodes: dict[str, dict[str, Any]] = {}
        self.project = Transformer.from_crs(CRS_WGS84, CRS_METRIC, always_xy=True)
        self.highway_way_count = 0
        self.skipped_invalid_location = 0

    def _save_tags(self, object_type: str, object_id: int, tags) -> None:
        if object_id in self.target_ids:
            self.tag_candidates[object_id].append((object_type, dict(tags)))

    def node(self, node) -> None:
        self._save_tags("node", node.id, node.tags)
        tags = dict(node.tags)
        entrance = tags.get("entrance")
        barrier = tags.get("barrier")
        is_main_entrance = entrance == "main"
        is_named_gate = barrier in {"gate", "lift_gate", "swing_gate", "kissing_gate"} and bool(tags.get("name"))
        if not (is_main_entrance or is_named_gate):
            return
        try:
            if not node.location.valid():
                return
            point = Point(node.lon, node.lat)
        except osmium.InvalidLocationError:
            return
        if not self.prepared_mask.covers(point):
            return
        self.entrance_candidates.append(
            {
                "osm_id": str(node.id),
                "osm_object_type": "node",
                "name": tags.get("name"),
                "facility_type": "main_entrance" if is_main_entrance else barrier,
                "source_layer": "jiangsu-260920.osm.pbf",
                "longitude": point.x,
                "latitude": point.y,
                "geometry": point,
            }
        )

    def relation(self, relation) -> None:
        self._save_tags("relation", relation.id, relation.tags)

    def way(self, way) -> None:
        self._save_tags("way", way.id, way.tags)
        if way.id not in self.road_way_ids:
            return
        tags = dict(way.tags)
        if "highway" not in tags or len(way.nodes) < 2:
            return
        self.highway_way_count += 1
        node_iter = iter(way.nodes)
        left = next(node_iter)
        for segment_index, right in enumerate(node_iter):
            current_left = left
            left = right
            try:
                if not current_left.location.valid() or not right.location.valid():
                    self.skipped_invalid_location += 1
                    continue
                left_xy = (current_left.lon, current_left.lat)
                right_xy = (right.lon, right.lat)
            except osmium.InvalidLocationError:
                self.skipped_invalid_location += 1
                continue
            raw_segment = LineString([left_xy, right_xy])
            if not self.prepared_mask.intersects(raw_segment):
                continue
            clipped = raw_segment.intersection(self.mask)
            for part_index, part in enumerate(line_parts(clipped)):
                if part.is_empty or len(part.coords) < 2:
                    continue
                start = tuple(part.coords[0])
                end = tuple(part.coords[-1])
                from_id = self._endpoint_id(start, left_xy, right_xy, current_left.ref, right.ref)
                to_id = self._endpoint_id(end, left_xy, right_xy, current_left.ref, right.ref)
                if from_id == to_id:
                    continue
                metric = transform_geometry(self.project.transform, part)
                length_m = float(metric.length)
                if not math.isfinite(length_m) or length_m <= 0:
                    continue
                edge_id = f"w{way.id}_s{segment_index}_p{part_index}"
                record = {
                    "edge_id": edge_id,
                    "osm_way_id": str(way.id),
                    "from_id": from_id,
                    "to_id": to_id,
                    "length_m": round(length_m, 3),
                }
                for key in ROAD_TAGS:
                    record[key] = tags.get(key)
                self.edges.append(record)
                self.edge_geometries.append(part)
                self._remember_node(from_id, start)
                self._remember_node(to_id, end)

    @staticmethod
    def _endpoint_id(point, left_xy, right_xy, left_id: int, right_id: int) -> str:
        tolerance = 1e-10
        if abs(point[0] - left_xy[0]) < tolerance and abs(point[1] - left_xy[1]) < tolerance:
            return f"n{left_id}"
        if abs(point[0] - right_xy[0]) < tolerance and abs(point[1] - right_xy[1]) < tolerance:
            return f"n{right_id}"
        return stable_clip_node_id(point[0], point[1])

    def _remember_node(self, node_id: str, coordinate) -> None:
        if node_id in self.nodes:
            return
        is_clip = node_id.startswith("clip_")
        self.nodes[node_id] = {
            "node_id": node_id,
            "osm_node_id": None if is_clip else node_id[1:],
            "is_clip_node": is_clip,
            "longitude": coordinate[0],
            "latitude": coordinate[1],
            "geometry": Point(coordinate),
        }


def select_pbf_tags(
    candidates: list[tuple[str, dict[str, str]]] | None,
    preferred_types: tuple[str, ...],
) -> tuple[str | None, dict[str, str]]:
    if not candidates:
        return None, {}
    by_type = {kind: tags for kind, tags in candidates}
    for kind in preferred_types:
        if kind in by_type:
            return kind, by_type[kind]
    return candidates[0]


def build_water(
    water_areas: gpd.GeoDataFrame,
    waterways: gpd.GeoDataFrame,
    candidates: dict[int, list[tuple[str, dict[str, str]]]],
    processed_at: str,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    rows: list[dict[str, Any]] = []
    geometries = []
    for layer_name, frame, preferred in (
        ("gis_osm_water_a_free", water_areas, ("relation", "way")),
        ("gis_osm_waterways_free", waterways, ("way",)),
    ):
        for _, source in frame.iterrows():
            osm_id = normalize_osm_id(source.get("osm_id"))
            object_type, tags = select_pbf_tags(candidates.get(osm_id), preferred)
            raw_name = source.get("name")
            row = {
                "water_id": f"{layer_name}_{source.get('osm_id')}",
                "osm_id": None if osm_id is None else str(osm_id),
                "osm_object_type": object_type,
                "name": tags.get("name") or (raw_name if isinstance(raw_name, str) else None),
                "water_type": tags.get("natural") or tags.get("waterway") or tags.get("water") or source.get("fclass"),
                "source_layer": layer_name,
                "source_date": SOURCE_DATE,
                "processed_at": processed_at,
                "representative_longitude": source.geometry.representative_point().x,
                "representative_latitude": source.geometry.representative_point().y,
            }
            rows.append(row)
            geometries.append(source.geometry)
    water = gpd.GeoDataFrame(rows, geometry=geometries, crs=CRS_WGS84)
    water_candidates = water[
        ["water_id", "osm_id", "name", "water_type", "representative_longitude", "representative_latitude"]
    ].copy()
    water_candidates.insert(0, "candidate_id", [f"WC{i:06d}" for i in range(1, len(water_candidates) + 1)])
    water_candidates["verification_status"] = "unverified"
    water_candidates["verified"] = None
    water_candidates["safety"] = None
    water_candidates["capacity"] = None
    water_candidates["adopted"] = None
    water_candidates["source_date"] = SOURCE_DATE
    water_candidates["longitude"] = water_candidates.pop("representative_longitude")
    water_candidates["latitude"] = water_candidates.pop("representative_latitude")
    water_candidates = gpd.GeoDataFrame(
        water_candidates,
        geometry=gpd.points_from_xy(water_candidates.longitude, water_candidates.latitude),
        crs=CRS_WGS84,
    )
    return water, water_candidates


def build_facilities(
    point_pois: gpd.GeoDataFrame,
    area_pois: gpd.GeoDataFrame,
    transport_points: gpd.GeoDataFrame,
    transport_areas: gpd.GeoDataFrame,
    candidates: dict[int, list[tuple[str, dict[str, str]]]],
    entrance_candidates: list[dict[str, Any]],
    processed_at: str,
) -> gpd.GeoDataFrame:
    frames = [
        ("gis_osm_pois_free", point_pois, ("node",)),
        ("gis_osm_pois_a_free", area_pois, ("relation", "way")),
        ("gis_osm_transport_free", transport_points, ("node",)),
        ("gis_osm_transport_a_free", transport_areas, ("relation", "way")),
    ]
    rows: list[dict[str, Any]] = []
    geometries: list[Point] = []
    for layer_name, frame, preferred in frames:
        if frame.empty:
            continue
        selected = frame.loc[frame["fclass"].isin(FACILITY_CLASSES)]
        for _, source in selected.iterrows():
            osm_id = normalize_osm_id(source.get("osm_id"))
            object_type, tags = select_pbf_tags(candidates.get(osm_id), preferred)
            point = source.geometry if isinstance(source.geometry, Point) else source.geometry.representative_point()
            raw_name = source.get("name")
            rows.append(
                {
                    "facility_id": f"F{len(rows) + 1:06d}",
                    "osm_id": None if osm_id is None else str(osm_id),
                    "osm_object_type": object_type,
                    "name": tags.get("name") or (raw_name if isinstance(raw_name, str) else None),
                    "facility_type": source.get("fclass"),
                    "source_layer": layer_name,
                    "verification_status": "unverified",
                    "operational_status": None,
                    "landing_capable": None,
                    "assembly_capable": None,
                    "source_date": SOURCE_DATE,
                    "processed_at": processed_at,
                    "longitude": point.x,
                    "latitude": point.y,
                }
            )
            geometries.append(point)
    for source in entrance_candidates:
        point = source["geometry"]
        rows.append(
            {
                "facility_id": f"F{len(rows) + 1:06d}",
                "osm_id": source["osm_id"],
                "osm_object_type": source["osm_object_type"],
                "name": source["name"],
                "facility_type": source["facility_type"],
                "source_layer": source["source_layer"],
                "verification_status": "unverified",
                "operational_status": None,
                "landing_capable": None,
                "assembly_capable": None,
                "source_date": SOURCE_DATE,
                "processed_at": processed_at,
                "longitude": source["longitude"],
                "latitude": source["latitude"],
            }
        )
        geometries.append(point)
    return gpd.GeoDataFrame(rows, geometry=geometries, crs=CRS_WGS84)


def write_geojson(frame: gpd.GeoDataFrame, path: Path) -> None:
    frame.to_file(path, driver="GeoJSON", encoding="UTF-8", index=False)


def create_qa_figure(mask, roads, water, facilities, output: Path) -> bool:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    fig, axis = plt.subplots(figsize=(10, 8), dpi=180)
    gpd.GeoSeries([mask], crs=CRS_WGS84).boundary.plot(ax=axis, color="black", linewidth=1.0, label="Nanjing + 5 km")
    if not water.empty:
        water.plot(ax=axis, color="#3690c0", linewidth=0.35, alpha=0.55)
    if not roads.empty:
        roads.plot(ax=axis, color="#f16913", linewidth=0.12, alpha=0.50)
    if not facilities.empty:
        facilities.plot(ax=axis, color="#238b45", markersize=3, alpha=0.8)
    axis.set_title("Nanjing OSM delivery overlay QA")
    axis.set_xlabel("Longitude")
    axis.set_ylabel("Latitude")
    axis.set_aspect("equal")
    fig.tight_layout()
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)
    return True


def main() -> None:
    args = parse_args()
    for required in (args.boundary, args.gpkg, args.pbf):
        if not required.exists():
            raise FileNotFoundError(required)
    args.output.mkdir(parents=True, exist_ok=True)
    processed_at = utc_now()
    mask = load_delivery_mask(args.boundary)

    print("[1/6] Reading and clipping GeoPackage layers")
    layer_names = (
        "gis_osm_roads_free",
        "gis_osm_water_a_free",
        "gis_osm_waterways_free",
        "gis_osm_pois_free",
        "gis_osm_pois_a_free",
        "gis_osm_transport_free",
        "gis_osm_transport_a_free",
    )
    layers = {name: read_and_clip(args.gpkg, name, mask) for name in layer_names}
    target_ids: set[int] = set()
    for frame in layers.values():
        target_ids.update(
            osm_id
            for osm_id in (normalize_osm_id(value) for value in frame.get("osm_id", []))
            if osm_id is not None
        )

    road_way_ids = {
        osm_id
        for osm_id in (
            normalize_osm_id(value)
            for value in layers["gis_osm_roads_free"].get("osm_id", [])
        )
        if osm_id is not None
    }

    print("[2/6] Scanning PBF for roads, topology, and unsimplified tags")
    collector = OSMCollector(mask, target_ids, road_way_ids)
    collector.apply_file(str(args.pbf), locations=True)
    roads = gpd.GeoDataFrame(collector.edges, geometry=collector.edge_geometries, crs=CRS_WGS84)
    road_nodes = gpd.GeoDataFrame(list(collector.nodes.values()), crs=CRS_WGS84)

    print("[3/6] Building water and facility candidate products")
    water, water_candidates = build_water(
        layers["gis_osm_water_a_free"],
        layers["gis_osm_waterways_free"],
        collector.tag_candidates,
        processed_at,
    )
    facilities = build_facilities(
        layers["gis_osm_pois_free"],
        layers["gis_osm_pois_a_free"],
        layers["gis_osm_transport_free"],
        layers["gis_osm_transport_a_free"],
        collector.tag_candidates,
        collector.entrance_candidates,
        processed_at,
    )

    print("[4/6] Writing delivery files")
    paths = {
        "roads": args.output / "roads.geojson",
        "road_nodes": args.output / "road_nodes.geojson",
        "water_bodies": args.output / "water_bodies.geojson",
        "water_candidates": args.output / "water_candidates.geojson",
        "facilities": args.output / "facilities.geojson",
        "coverage_gaps": args.output / "coverage_gaps.json",
        "metadata": args.output / "nanjing_osm_metadata.csv",
        "qa_report": args.output / "nanjing_osm_qa_report.md",
        "qa_overlay": args.output / "nanjing_osm_qa_overlay.png",
        "manifest": args.output / "manifest.json",
    }
    write_geojson(roads, paths["roads"])
    write_geojson(road_nodes, paths["road_nodes"])
    write_geojson(water, paths["water_bodies"])
    write_geojson(water_candidates, paths["water_candidates"])
    write_geojson(facilities, paths["facilities"])

    road_node_ids = set(road_nodes["node_id"])
    missing_refs = set(roads["from_id"]) | set(roads["to_id"])
    missing_refs -= road_node_ids
    invalid_road_geometries = int((~roads.geometry.is_valid | roads.geometry.is_empty).sum())
    invalid_water_geometries = int((~water.geometry.is_valid | water.geometry.is_empty).sum())
    nonpositive_lengths = int((roads["length_m"] <= 0).sum())
    qa_pass = not (missing_refs or invalid_road_geometries or invalid_water_geometries or nonpositive_lengths)
    qa_status = "PASS" if qa_pass else "FAIL"

    coverage_gaps = {
        "region_id": "nanjing",
        "extent": "Nanjing administrative boundary plus 5 km",
        "generated_at": processed_at,
        "items": [
            {
                "dataset": "water_candidates",
                "gap": "Public OSM geometry does not prove current safety, capacity, or practical water access.",
                "handling": "Candidate fields remain null and verification_status is unverified.",
            },
            {
                "dataset": "facilities",
                "gap": "Public OSM features do not prove landing, assembly, staffing, or current operational capability.",
                "handling": "Operational capability fields remain null; candidates require field verification.",
            },
            {
                "dataset": "roads",
                "gap": "Missing OSM access tags mean unknown, not unrestricted access; the graph is not production navigation.",
                "handling": "Raw access/foot/motor_vehicle tags are retained without inferred defaults.",
            },
        ],
    }
    paths["coverage_gaps"].write_text(
        json.dumps(coverage_gaps, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    metadata_rows = [
        {
            "dataset_id": "nanjing_osm_roads_20260920",
            "file": paths["roads"].name,
            "source_url": SOURCE_URL,
            "source_version": "geofabrik-jiangsu-260920-pbf",
            "downloaded_at": SOURCE_DATE,
            "license": OSM_LICENSE,
            "crs": CRS_WGS84,
            "metric_processing_crs": CRS_METRIC,
            "resolution_or_scale": "vector; OSM source detail",
            "processing": "PBF highway ways split at original consecutive OSM nodes and clipped to Nanjing + 5 km; lengths calculated in EPSG:32650",
            "feature_count": len(roads),
            "qa_status": qa_status,
        },
        {
            "dataset_id": "nanjing_osm_water_20260920",
            "file": paths["water_bodies"].name,
            "source_url": SOURCE_URL,
            "source_version": "geofabrik-jiangsu-260920-gpkg+pbf-tags",
            "downloaded_at": SOURCE_DATE,
            "license": OSM_LICENSE,
            "crs": CRS_WGS84,
            "metric_processing_crs": "not_applicable",
            "resolution_or_scale": "vector; OSM source detail",
            "processing": "GeoPackage water polygons and waterways clipped to Nanjing + 5 km; names/types recovered from PBF where available",
            "feature_count": len(water),
            "qa_status": qa_status,
        },
        {
            "dataset_id": "nanjing_osm_facility_candidates_20260920",
            "file": paths["facilities"].name,
            "source_url": SOURCE_URL,
            "source_version": "geofabrik-jiangsu-260920-gpkg+pbf-tags",
            "downloaded_at": SOURCE_DATE,
            "license": OSM_LICENSE,
            "crs": CRS_WGS84,
            "metric_processing_crs": "not_applicable",
            "resolution_or_scale": "vector; OSM source detail",
            "processing": "Selected public POI/transport classes converted to candidate points; no operational capability inferred",
            "feature_count": len(facilities),
            "qa_status": qa_status,
        },
    ]
    pd.DataFrame(metadata_rows).to_csv(paths["metadata"], index=False, encoding="utf-8-sig")

    print("[5/6] Creating QA products")
    overlay_created = create_qa_figure(mask, roads, water, facilities, paths["qa_overlay"])
    highway_counts = Counter(roads["highway"].fillna("unknown"))
    qa_lines = [
        "# Nanjing OSM delivery QA report",
        "",
        f"- Generated at: `{processed_at}`",
        f"- Processing extent: Nanjing administrative boundary plus 5 km",
        f"- QA status: **{qa_status}**",
        f"- Road edges: {len(roads):,}",
        f"- Road nodes: {len(road_nodes):,}",
        f"- Water geometries: {len(water):,}",
        f"- Water candidates: {len(water_candidates):,}",
        f"- Facility candidates: {len(facilities):,}",
        f"- Missing road-node references: {len(missing_refs):,}",
        f"- Invalid or empty road geometries: {invalid_road_geometries:,}",
        f"- Invalid or empty water geometries: {invalid_water_geometries:,}",
        f"- Non-positive road lengths: {nonpositive_lengths:,}",
        f"- PBF segments skipped for invalid node location: {collector.skipped_invalid_location:,}",
        f"- Overlay image created: {overlay_created}",
        "",
        "## Top road classes",
        "",
    ]
    qa_lines.extend(f"- `{key}`: {value:,}" for key, value in highway_counts.most_common(20))
    qa_lines.extend(
        [
            "",
            "## Interpretation limits",
            "",
            "Road connectivity follows shared OSM node IDs. Grade-separated crossings are not connected unless the source data shares a node. The result is a reproducible candidate graph, not a claim of production-grade evacuation navigation.",
            "",
            "Water and facility records are candidates. `unverified` and null capability fields must not be promoted to usable/available without external evidence or field verification.",
            "",
        ]
    )
    paths["qa_report"].write_text("\n".join(qa_lines), encoding="utf-8")

    print("[6/6] Hashing outputs and writing manifest")
    output_entries = []
    for name, path in paths.items():
        if name == "manifest" or not path.exists():
            continue
        output_entries.append(
            {
                "role": name,
                "path": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
        )
    manifest = {
        "delivery_id": "nanjing-osm-20260920",
        "region_id": "nanjing",
        "extent": "Nanjing administrative boundary plus 5 km",
        "generated_at": processed_at,
        "qa_status": qa_status,
        "source": {
            "provider": "Geofabrik / OpenStreetMap contributors",
            "url": SOURCE_URL,
            "source_date": SOURCE_DATE,
            "license": OSM_LICENSE,
            "pbf": {
                "path": str(args.pbf.relative_to(args.root)),
                "bytes": args.pbf.stat().st_size,
                "sha256": sha256(args.pbf),
            },
            "gpkg": {
                "path": str(args.gpkg.relative_to(args.root)),
                "bytes": args.gpkg.stat().st_size,
                "sha256": sha256(args.gpkg),
            },
            "boundary": {
                "path": str(args.boundary.relative_to(args.root)),
                "bytes": args.boundary.stat().st_size,
                "sha256": sha256(args.boundary),
            },
        },
        "outputs": output_entries,
    }
    paths["manifest"].write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"qa_status": qa_status, "output": str(args.output), "counts": {
        "roads": len(roads), "road_nodes": len(road_nodes), "water": len(water),
        "water_candidates": len(water_candidates), "facilities": len(facilities)
    }}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
