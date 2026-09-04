# -*- coding: utf-8 -*-
"""
森林火灾环境数据服务
输入火点经纬度，统一返回地形、天气、土地覆盖、水源和道路信息。
"""

from pathlib import Path
from collections import Counter
import math
import time

import numpy as np
import requests
import rasterio
import planetary_computer as pc

from pyproj import Transformer
from shapely.geometry import Point, LineString
from pystac_client import Client
from rasterio.windows import Window
from rasterio.transform import xy
from rasterio.warp import transform


# environment_service.py 位于 后端/app/services/
# 默认 DEM 位于 后端/N32E118.hgt
DEFAULT_DEM_PATH = Path(__file__).resolve().parents[2] / "N32E118.hgt"

DEFAULT_WATER_RADIUS_M = 5000
DEFAULT_ROAD_RADIUS_M = 5000

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
# 主源在国内网络常被重置；mail.ru 镜像经实测含完整中国数据（紫霞湖/黄马水库等）
OVERPASS_MIRROR_URLS = (
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
)

WORLD_COVER_CLASSES = {
    10: "Tree Cover",
    20: "Shrubland",
    30: "Grassland",
    40: "Cropland",
    50: "Built-up",
    60: "Bare / Sparse Vegetation",
    70: "Snow and Ice",
    80: "Permanent Water Bodies",
    90: "Herbaceous Wetland",
    95: "Mangroves",
    100: "Moss and Lichen",
}

BURNABLE_NATURAL = {10, 20, 30}
PREFERRED_WATER_TYPES = {"reservoir", "lake", "pond"}

ALL_HIGHWAY_TYPES = {
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "unclassified", "residential", "service", "track",
    "path", "footway", "steps", "cycleway",
}

VEHICLE_HIGHWAY_TYPES = {
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "unclassified", "residential", "service", "track",
}


# ---------- 公共函数 ----------

def validate_coordinates(latitude, longitude):
    try:
        latitude = float(latitude)
        longitude = float(longitude)
    except (TypeError, ValueError) as exc:
        raise ValueError("经纬度必须是数字") from exc

    if not -90 <= latitude <= 90:
        raise ValueError("latitude 必须位于 -90 到 90 之间")
    if not -180 <= longitude <= 180:
        raise ValueError("longitude 必须位于 -180 到 180 之间")

    return latitude, longitude


def degree_to_direction(deg):
    if deg is None:
        return None
    directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return directions[int((float(deg) + 22.5) // 45) % 8]


def get_utm_epsg(latitude, longitude):
    zone = int((longitude + 180) // 6) + 1
    return (32600 if latitude >= 0 else 32700) + zone


def haversine_distance_m(lat1, lon1, lat2, lon2):
    radius = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)

    a = (
        math.sin(dp / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def overpass_query(query, timeout=30, retries=2):
    last_error = None

    # 主源被墙时连接级错误毫秒级暴露，重试 1 次即快速切换镜像；镜像保留完整退避重试
    for url, attempts in ((OVERPASS_URL, 1), *((u, retries) for u in OVERPASS_MIRROR_URLS)):
        for attempt in range(attempts):
            try:
                response = requests.post(
                    url,
                    data={"data": query},
                    headers={"User-Agent": "ForestFire-EnvironmentTool/1.0"},
                    timeout=(3, timeout),
                )
                response.raise_for_status()
                return response.json().get("elements", [])
            except requests.RequestException as exc:
                last_error = exc
                if attempt < attempts - 1:
                    time.sleep(2 ** (attempt + 1))

    raise RuntimeError(f"Overpass 请求失败: {last_error}")


def safe_call(func, *args, **kwargs):
    try:
        return {"status": "ok", **func(*args, **kwargs)}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


# ---------- 地形 ----------

def get_terrain(latitude, longitude, dem_path, window_size=5):
    dem_path = Path(dem_path)

    if not dem_path.is_file():
        raise FileNotFoundError(f"未找到 DEM 文件: {dem_path}")

    with rasterio.open(dem_path) as dataset:
        if dataset.crs is None:
            raise RuntimeError("DEM 缺少 CRS")

        to_dem = Transformer.from_crs("EPSG:4326", dataset.crs, always_xy=True)
        x0, y0 = to_dem.transform(longitude, latitude)

        if not (
            dataset.bounds.left <= x0 <= dataset.bounds.right
            and dataset.bounds.bottom <= y0 <= dataset.bounds.top
        ):
            raise ValueError("输入坐标不在当前 DEM 覆盖范围内")

        row, col = dataset.index(x0, y0)
        half = window_size // 2
        window = Window(col - half, row - half, window_size, window_size)

        data = dataset.read(
            1, window=window, boundless=True, masked=True
        ).astype(float)

        center = data[data.shape[0] // 2, data.shape[1] // 2]
        if np.ma.is_masked(center):
            raise RuntimeError("中心像素没有有效高程值")

        rows, cols = np.indices(data.shape)
        xs, ys = xy(
            dataset.window_transform(window),
            rows,
            cols,
            offset="center",
        )

        z = data.filled(np.nan).ravel()
        x = np.asarray(xs, dtype=float).ravel()
        y = np.asarray(ys, dtype=float).ravel()
        valid = np.isfinite(z) & (~np.ma.getmaskarray(data).ravel())

        if valid.sum() < 3:
            raise RuntimeError("有效 DEM 像素不足")

        to_wgs84 = Transformer.from_crs(
            dataset.crs, "EPSG:4326", always_xy=True
        )
        lons, lats = to_wgs84.transform(x[valid], y[valid])

        epsg = get_utm_epsg(latitude, longitude)
        to_utm = Transformer.from_crs(
            "EPSG:4326", f"EPSG:{epsg}", always_xy=True
        )
        east, north = to_utm.transform(lons, lats)

        east = np.asarray(east, dtype=float)
        north = np.asarray(north, dtype=float)
        east -= east.mean()
        north -= north.mean()

        matrix = np.column_stack([east, north, np.ones_like(east)])
        dz_dx, dz_dy, _ = np.linalg.lstsq(
            matrix, z[valid], rcond=None
        )[0]

        slope_deg = math.degrees(
            math.atan(math.hypot(dz_dx, dz_dy))
        )

        if slope_deg < 0.1:
            down_deg = None
            up_deg = None
        else:
            down_deg = (
                math.degrees(math.atan2(-dz_dx, -dz_dy)) + 360
            ) % 360
            up_deg = (down_deg + 180) % 360

    return {
        "elevation_m": round(float(center), 1),
        "slope_deg": round(slope_deg, 2),
        "downslope_deg": None if down_deg is None else round(down_deg, 1),
        "downslope_direction": degree_to_direction(down_deg),
        "upslope_deg": None if up_deg is None else round(up_deg, 1),
        "upslope_direction": degree_to_direction(up_deg),
    }


# ---------- 天气 ----------

def get_weather(latitude, longitude):
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": ",".join([
            "temperature_2m",
            "relative_humidity_2m",
            "precipitation",
            "wind_speed_10m",
            "wind_direction_10m",
            "wind_gusts_10m",
        ]),
        "timezone": "auto",
        "wind_speed_unit": "ms",
    }

    response = requests.get(
        OPEN_METEO_URL,
        params=params,
        timeout=(3, 15),
    )
    response.raise_for_status()

    data = response.json()
    current = data.get("current", {})

    wind_from_deg = current.get("wind_direction_10m")
    wind_to_deg = (
        None
        if wind_from_deg is None
        else (float(wind_from_deg) + 180) % 360
    )

    return {
        "time": current.get("time"),
        "temperature_c": current.get("temperature_2m"),
        "relative_humidity_pct": current.get("relative_humidity_2m"),
        "precipitation_mm": current.get("precipitation"),
        "wind_speed_m_s": current.get("wind_speed_10m"),
        "wind_from_deg": wind_from_deg,
        "wind_from_direction": degree_to_direction(wind_from_deg),
        "wind_to_deg": None if wind_to_deg is None else round(wind_to_deg, 1),
        "wind_to_direction": degree_to_direction(wind_to_deg),
        "wind_gust_m_s": current.get("wind_gusts_10m"),
        "timezone": data.get("timezone"),
    }


# ---------- 土地覆盖 ----------

def get_landcover(
    latitude,
    longitude,
    window_size=11,
    min_burnable_ratio=0.4,
):
    catalog = Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1",
        modifier=pc.sign_inplace,
    )

    search = catalog.search(
        collections=["esa-worldcover"],
        intersects={
            "type": "Point",
            "coordinates": [longitude, latitude],
        },
    )

    item = next(search.items(), None)
    if item is None:
        raise RuntimeError("当前位置没有找到 ESA WorldCover 数据")

    asset = item.assets.get("map") or next(iter(item.assets.values()))

    with rasterio.open(asset.href) as dataset:
        xs, ys = transform(
            "EPSG:4326",
            dataset.crs,
            [longitude],
            [latitude],
        )
        row, col = dataset.index(xs[0], ys[0])

        center = int(
            dataset.read(
                1,
                window=Window(col, row, 1, 1),
                boundless=True,
                fill_value=0,
            )[0, 0]
        )

        half = window_size // 2
        data = dataset.read(
            1,
            window=Window(
                col - half,
                row - half,
                window_size,
                window_size,
            ),
            boundless=True,
            fill_value=0,
        )

    valid = data[data != 0]
    if valid.size == 0:
        raise RuntimeError("WorldCover 返回窗口中没有有效像素")

    counts = Counter(valid.ravel().tolist())
    dominant = int(counts.most_common(1)[0][0])

    burnable_ratio = float(
        np.isin(valid, list(BURNABLE_NATURAL)).sum() / valid.size
    )

    return {
        "center_class": WORLD_COVER_CLASSES.get(center, "Unknown"),
        "dominant_class": WORLD_COVER_CLASSES.get(dominant, "Unknown"),
        "burnable_ratio": round(burnable_ratio, 3),
        "fuel_possible": burnable_ratio >= min_burnable_ratio,
    }


# ---------- 水源 ----------

def classify_water(tags):
    if (
        tags.get("landuse") == "reservoir"
        or tags.get("water") == "reservoir"
    ):
        return "reservoir"

    if tags.get("water") in {"lake", "pond"}:
        return tags["water"]

    if tags.get("waterway") in {"river", "stream"}:
        return tags["waterway"]

    return tags.get("water") or "water"


def water_name(tags, source_type):
    name = (
        tags.get("name:zh")
        or tags.get("name")
        or tags.get("ref")
    )

    if name:
        return name

    unnamed = {
        "stream": "未命名溪流",
        "river": "未命名河流",
        "reservoir": "未命名水库",
        "lake": "未命名湖泊",
        "pond": "未命名池塘",
        "water": "未命名水体",
    }
    return unnamed.get(source_type, "未命名水体")


def get_water_sources(
    latitude,
    longitude,
    search_radius_m=DEFAULT_WATER_RADIUS_M,
):
    query = f"""
    [out:json][timeout:25];
    (
      nwr(around:{search_radius_m},{latitude},{longitude})["natural"="water"];
      nwr(around:{search_radius_m},{latitude},{longitude})["landuse"="reservoir"];
      nwr(around:{search_radius_m},{latitude},{longitude})["waterway"="river"];
      nwr(around:{search_radius_m},{latitude},{longitude})["waterway"="stream"];
    );
    out tags center;
    """

    features = []

    for element in overpass_query(query):
        tags = element.get("tags", {})
        center = (
            element
            if "lat" in element and "lon" in element
            else element.get("center", {})
        )

        lat = center.get("lat")
        lon = center.get("lon")
        if lat is None or lon is None:
            continue

        source_type = classify_water(tags)

        features.append({
            "name": water_name(tags, source_type),
            "type": source_type,
            "latitude": round(float(lat), 6),
            "longitude": round(float(lon), 6),
            "distance_m": round(
                haversine_distance_m(
                    latitude,
                    longitude,
                    lat,
                    lon,
                ),
                1,
            ),
        })

    features.sort(key=lambda item: item["distance_m"])
    preferred = [
        item
        for item in features
        if item["type"] in PREFERRED_WATER_TYPES
    ]

    return {
        "found": bool(features),
        "feature_count": len(features),
        # 全量水体按距离排序截断，供前端真实地图全量打点（契约：只增不破）。
        "features": features[:20],
        "nearest": features[0] if features else None,
        "preferred": preferred[0] if preferred else None,
        "distance_note": "到 OSM 水体代表点的近似距离",
    }


# ---------- 道路 ----------

def road_name(tags):
    name = (
        tags.get("name:zh")
        or tags.get("name")
        or tags.get("ref")
    )

    if name:
        return name

    unnamed = {
        "service": "未命名服务道路",
        "track": "未命名林区/土路",
        "path": "未命名小径",
        "footway": "未命名步道",
        "steps": "未命名台阶",
    }
    return unnamed.get(tags.get("highway"), "未命名道路")


def line_distance(latitude, longitude, geometry):
    if not geometry or len(geometry) < 2:
        return None

    epsg = get_utm_epsg(latitude, longitude)
    to_utm = Transformer.from_crs(
        "EPSG:4326",
        f"EPSG:{epsg}",
        always_xy=True,
    )
    to_wgs84 = Transformer.from_crs(
        f"EPSG:{epsg}",
        "EPSG:4326",
        always_xy=True,
    )

    fire_x, fire_y = to_utm.transform(longitude, latitude)

    road_xy = [
        to_utm.transform(point["lon"], point["lat"])
        for point in geometry
        if "lat" in point and "lon" in point
    ]

    if len(road_xy) < 2:
        return None

    line = LineString(road_xy)
    fire = Point(fire_x, fire_y)
    nearest = line.interpolate(line.project(fire))

    near_lon, near_lat = to_wgs84.transform(
        nearest.x,
        nearest.y,
    )

    return {
        "distance_m": round(float(fire.distance(line)), 1),
        "nearest_point": {
            "latitude": round(float(near_lat), 6),
            "longitude": round(float(near_lon), 6),
        },
    }


def get_road_context(
    latitude,
    longitude,
    search_radius_m=DEFAULT_ROAD_RADIUS_M,
):
    highway_regex = "|".join(sorted(ALL_HIGHWAY_TYPES))

    query = f"""
    [out:json][timeout:25];
    way(around:{search_radius_m},{latitude},{longitude})
      ["highway"~"^({highway_regex})$"];
    out tags geom;
    """

    roads = []

    for element in overpass_query(query):
        tags = element.get("tags", {})
        distance = line_distance(
            latitude,
            longitude,
            element.get("geometry", []),
        )

        if distance is None:
            continue

        roads.append({
            "name": road_name(tags),
            "highway": tags.get("highway"),
            "surface": tags.get("surface"),
            "access": tags.get("access"),
            "motor_vehicle": tags.get("motor_vehicle"),
            **distance,
        })

    roads.sort(key=lambda item: item["distance_m"])

    vehicle_candidates = [
        road
        for road in roads
        if road["highway"] in VEHICLE_HIGHWAY_TYPES
        and road["access"] != "no"
        and road["motor_vehicle"] != "no"
    ]

    return {
        "found": bool(roads),
        "road_count": len(roads),
        "nearest_transport": roads[0] if roads else None,
        "nearest_vehicle_access_candidate": (
            vehicle_candidates[0]
            if vehicle_candidates
            else None
        ),
    }


# ---------- 总入口 ----------

def get_environment(
    latitude,
    longitude,
    dem_path=None,
    water_radius_m=DEFAULT_WATER_RADIUS_M,
    road_radius_m=DEFAULT_ROAD_RADIUS_M,
):
    """
    输入火点经纬度，返回统一环境数据。
    """

    try:
        latitude, longitude = validate_coordinates(
            latitude,
            longitude,
        )
    except ValueError as exc:
        return {
            "status": "invalid_input",
            "error": str(exc),
            "location": {
                "latitude": latitude,
                "longitude": longitude,
            },
        }

    dem_path = (
        Path(dem_path)
        if dem_path is not None
        else DEFAULT_DEM_PATH
    )

    modules = {
        "terrain": safe_call(
            get_terrain,
            latitude,
            longitude,
            dem_path,
        ),
        "weather": safe_call(
            get_weather,
            latitude,
            longitude,
        ),
        "landcover": safe_call(
            get_landcover,
            latitude,
            longitude,
        ),
        "water": safe_call(
            get_water_sources,
            latitude,
            longitude,
            water_radius_m,
        ),
        "road": safe_call(
            get_road_context,
            latitude,
            longitude,
            road_radius_m,
        ),
    }

    ok_count = sum(
        module["status"] == "ok"
        for module in modules.values()
    )

    if ok_count == len(modules):
        status = "ok"
    elif ok_count > 0:
        status = "partial"
    else:
        status = "error"

    return {
        "status": status,
        "location": {
            "latitude": latitude,
            "longitude": longitude,
        },
        **modules,
        "sources": {
            "terrain": "NASA SRTM",
            "weather": "Open-Meteo",
            "landcover": (
                "ESA WorldCover / "
                "Microsoft Planetary Computer"
            ),
            "water": "OpenStreetMap / Overpass API",
            "road": "OpenStreetMap / Overpass API",
        },
    }
