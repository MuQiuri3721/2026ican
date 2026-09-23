# -*- coding: utf-8 -*-
"""
森林火灾环境数据服务
输入火点经纬度，统一返回地形、天气、土地覆盖、水源和道路信息。
"""

from pathlib import Path
from collections import Counter
import json
import math
import os
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


# ---------- 离线地理数据包（geo-delivery-v2，BE-52） ----------
# GEO_DATA_ROOT 指向交付包根目录（含 data/nanjing/...）；
# GEO_DATA_MODE = live（默认，纯在线）/ auto（覆盖范围内离线优先、范围外回退在线）/ offline（仅离线）。
# 未设置 GEO_DATA_ROOT 时恒为 live，行为与历史版本完全一致。

GEO_DELIVERY_FILES = {
    "dem": "data/nanjing/srtm/nanjing_srtmgl1_003_30m_epsg32650_dem.tif",
    "slope": "data/nanjing/srtm/nanjing_srtmgl1_003_30m_epsg32650_slope.tif",
    "aspect": "data/nanjing/srtm/nanjing_srtmgl1_003_30m_epsg32650_aspect.tif",
    "landcover": "data/nanjing/worldcover/nanjing_worldcover_2021_v200_10m_epsg32650_landcover.tif",
    "water_candidates": "data/nanjing/osm/water_candidates.geojson",
    "weather_current": "data/nanjing/weather/weather_current.json",
}

# 南京行政边界+5km 的粗略外扩矩形（WGS84），仅用于 auto 模式判断离线气象是否适用
GEO_DELIVERY_CITY_BBOX_WGS84 = (31.0, 118.1, 32.8, 119.7)  # (min_lat, min_lon, max_lat, max_lon)

# 交付包 SRTM 裁剪范围为南京市边界 + 5km（EPSG:32650），粗略外扩矩形用于快速覆盖预判
GEO_DELIVERY_COVER_BBOX_EPSG32650 = (623430, 3451650, 716730, 3614460)


def geo_data_root():
    raw = os.environ.get("GEO_DATA_ROOT", "").strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        # 相对路径按仓库根（backend/ 上一级）解析：clone 到任意位置 .env 无需改动
        path = Path(__file__).resolve().parents[3] / path
    return path


def geo_data_mode():
    mode = os.environ.get("GEO_DATA_MODE", "").strip().lower()
    if mode in {"live", "auto", "offline"}:
        return mode
    return "auto" if geo_data_root() else "live"


def offline_geo_file(kind):
    """返回交付包内指定成果的路径；未配置或文件缺失返回 None。"""
    root = geo_data_root()
    if root is None:
        return None
    path = root / GEO_DELIVERY_FILES[kind]
    return path if path.is_file() else None


def get_terrain_offline(latitude, longitude):
    """从交付包 SRTM 成果采样高程 + GEE 预计算坡度/坡向（30m，EPSG:32650）。"""
    paths = {kind: offline_geo_file(kind) for kind in ("dem", "slope", "aspect")}
    missing = [kind for kind, path in paths.items() if path is None]
    if missing:
        raise RuntimeError(f"离线地形数据缺失: {missing}")

    to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32650", always_xy=True)
    x, y = to_utm.transform(longitude, latitude)

    values = {}
    for kind, path in paths.items():
        with rasterio.open(path) as dataset:
            row, col = dataset.index(x, y)
            if not (0 <= row < dataset.height and 0 <= col < dataset.width):
                raise ValueError("输入坐标不在离线地形数据覆盖范围内")
            value = dataset.read(
                1, window=Window(col, row, 1, 1), boundless=True, masked=True
            )[0, 0]
            if np.ma.is_masked(value) or not np.isfinite(float(value)):
                raise ValueError("离线地形数据在该坐标为 NoData")
            values[kind] = float(value)

    slope_deg = values["slope"]
    if slope_deg < 0.1:
        down_deg = None
        up_deg = None
    else:
        down_deg = values["aspect"] % 360
        up_deg = (down_deg + 180) % 360

    return {
        "elevation_m": round(values["dem"], 1),
        "slope_deg": round(slope_deg, 2),
        "downslope_deg": None if down_deg is None else round(down_deg, 1),
        "downslope_direction": degree_to_direction(down_deg),
        "upslope_deg": None if up_deg is None else round(up_deg, 1),
        "upslope_direction": degree_to_direction(up_deg),
        "dem_source": "geo-delivery-v2 (NASA SRTMGL1 v003 30m)",
    }


def get_landcover_offline(
    latitude,
    longitude,
    window_size=11,
    min_burnable_ratio=0.4,
):
    """从交付包 WorldCover 2021 v200 本地 tif 采样，输出与在线版逐键一致。"""
    path = offline_geo_file("landcover")
    if path is None:
        raise RuntimeError("离线地表覆盖数据缺失")

    with rasterio.open(path) as dataset:
        xs, ys = transform("EPSG:4326", dataset.crs, [longitude], [latitude])
        row, col = dataset.index(xs[0], ys[0])
        if not (0 <= row < dataset.height and 0 <= col < dataset.width):
            raise ValueError("输入坐标不在离线地表覆盖数据覆盖范围内")

        center = int(
            dataset.read(
                1, window=Window(col, row, 1, 1), boundless=True, fill_value=0
            )[0, 0]
        )
        half = window_size // 2
        data = dataset.read(
            1,
            window=Window(col - half, row - half, window_size, window_size),
            boundless=True,
            fill_value=0,
        )

    valid = data[data != 0]
    if valid.size == 0:
        raise RuntimeError("离线 WorldCover 窗口中没有有效像素")

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
        "landcover_source": "geo-delivery-v2 (ESA WorldCover 2021 v200 10m)",
    }


def get_terrain_routed(latitude, longitude, dem_path):
    """按 GEO_DATA_MODE 路由地形查询；live 模式与历史行为完全一致。"""
    mode = geo_data_mode()
    if mode in {"auto", "offline"}:
        result = safe_call(get_terrain_offline, latitude, longitude)
        if result["status"] == "ok":
            return result
        if mode == "offline":
            return result
    return safe_call(get_terrain, latitude, longitude, dem_path)


def get_landcover_routed(latitude, longitude, window_size=11, min_burnable_ratio=0.4):
    mode = geo_data_mode()
    if mode in {"auto", "offline"}:
        result = safe_call(
            get_landcover_offline, latitude, longitude, window_size, min_burnable_ratio
        )
        if result["status"] == "ok":
            return result
        if mode == "offline":
            return result
    return safe_call(
        get_landcover, latitude, longitude, window_size, min_burnable_ratio
    )


# ---------- 离线气象 ----------

def get_weather_offline(latitude, longitude):
    """交付包 Open-Meteo 留档（当前天气 + 时间戳/stale 诚实标注），输出与在线版逐键一致。"""
    path = offline_geo_file("weather_current")
    if path is None:
        raise RuntimeError("离线气象数据缺失")

    data = json.loads(path.read_text(encoding="utf-8"))
    wind_from = data.get("wind_from_10m_deg")
    wind_to = data.get("wind_to_10m_deg")

    return {
        "time": data.get("valid_time"),
        "temperature_c": data.get("temperature_2m_c"),
        "relative_humidity_pct": data.get("relative_humidity_2m_pct"),
        "precipitation_mm": data.get("precipitation_current_interval_mm"),
        "wind_speed_m_s": data.get("wind_speed_10m_m_s"),
        "wind_from_deg": wind_from,
        "wind_from_direction": data.get("wind_from_10m_compass")
        or degree_to_direction(wind_from),
        "wind_to_deg": wind_to,
        "wind_to_direction": data.get("wind_to_10m_compass")
        or (None if wind_to is None else degree_to_direction(wind_to)),
        "wind_gust_m_s": data.get("wind_gusts_10m_m_s"),
        "timezone": (data.get("returned_grid") or {}).get("timezone"),
        "weather_source": (
            f"geo-delivery-v2 ({data.get('dataset_id', 'open-meteo 留档')}，"
            f"valid {data.get('valid_time')}，stale={data.get('stale')})"
        ),
    }


def get_weather_routed(latitude, longitude):
    mode = geo_data_mode()
    if mode in {"auto", "offline"}:
        in_city = (
            GEO_DELIVERY_CITY_BBOX_WGS84[0] <= latitude <= GEO_DELIVERY_CITY_BBOX_WGS84[2]
            and GEO_DELIVERY_CITY_BBOX_WGS84[1] <= longitude <= GEO_DELIVERY_CITY_BBOX_WGS84[3]
        )
        if mode == "offline" or in_city:
            result = safe_call(get_weather_offline, latitude, longitude)
            if result["status"] == "ok":
                return result
            if mode == "offline":
                return result
    return safe_call(get_weather, latitude, longitude)


# ---------- 离线水源候选 ----------

_WATER_CANDIDATES_CACHE = {"path": None, "mtime": None, "features": None}


def _load_water_candidates(path: Path):
    """解析并缓存 water_candidates.geojson（全城 ~9,400 点；按路径+mtime 失效）。"""
    stat = path.stat()
    cache = _WATER_CANDIDATES_CACHE
    if cache["path"] != path or cache["mtime"] != stat.st_mtime:
        data = json.loads(path.read_text(encoding="utf-8"))
        cache["path"] = path
        cache["mtime"] = stat.st_mtime
        cache["features"] = data.get("features", [])
    return cache["features"]


def get_water_candidates_offline(
    latitude,
    longitude,
    search_radius_m=DEFAULT_WATER_RADIUS_M,
):
    """交付包水源候选（含稳定 candidate_id，全部 unverified——地理存在 ≠ 可取水）。"""
    path = offline_geo_file("water_candidates")
    if path is None:
        raise RuntimeError("离线水源候选数据缺失")

    picked = []
    for feature in _load_water_candidates(path):
        props = feature.get("properties", {})
        lon = props.get("longitude")
        lat = props.get("latitude")
        if lon is None or lat is None:
            continue
        distance = haversine_distance_m(latitude, longitude, lat, lon)
        if distance > search_radius_m:
            continue
        picked.append({
            "osm_id": props.get("water_id")
            or props.get("candidate_id")
            or props.get("osm_id"),
            "provider": "osm / geo-delivery-v2",
            "verification_status": props.get("verification_status", "unverified"),
            "safety_status": props.get("safety"),
            "capacity_liters": props.get("capacity"),  # null=未知，非 0 耗尽
            "name": props.get("name") or "未命名水体",
            "type": props.get("water_type", "water"),
            "latitude": round(float(lat), 6),
            "longitude": round(float(lon), 6),
            "distance_m": round(distance, 1),
        })

    picked.sort(key=lambda item: item["distance_m"])
    preferred = [item for item in picked if item["type"] in PREFERRED_WATER_TYPES]

    return {
        "found": bool(picked),
        "feature_count": len(picked),
        "features": picked[:20],
        "nearest": picked[0] if picked else None,
        "preferred": preferred[0] if preferred else None,
        "distance_note": "到离线候选水源代表点的近似距离（geo-delivery-v2，全部 unverified）",
        "water_candidates_source": "geo-delivery-v2 (OSM water_candidates)",
    }


def get_water_sources_routed(latitude, longitude, search_radius_m):
    mode = geo_data_mode()
    if mode in {"auto", "offline"}:
        result = safe_call(
            get_water_candidates_offline, latitude, longitude, search_radius_m
        )
        if result["status"] == "ok":
            # offline 模式空结果也是答案；auto 模式半径内无候选时回退在线补充（可用性优先）
            if mode == "offline" or result.get("found"):
                return result
        elif mode == "offline":
            return result
    return safe_call(get_water_sources, latitude, longitude, search_radius_m)


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
            # 稳定 ID（OPT-P2-02）：OSM 对象类型+对象 ID，不随名称/排序变化；
            # OSM 水体默认是「候选」（unverified）——地理存在 ≠ 可取水。
            "osm_id": f"{element.get('type', 'n')}{element.get('id')}",
            "provider": "osm",
            "verification_status": "unverified",
            "safety_status": None,
            "capacity_liters": None,  # 未知容量存 null；0 表示已知耗尽
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


B6_ROADS_MAX = 60


def _cap_roads(roads, vehicle_candidates):
    """B-6 路网上限裁剪：车辆可通行优先（战术价值），余按距离补足，去重保序。"""
    picked_set = set()
    selected = []
    for road in list(vehicle_candidates) + list(roads):
        if len(selected) >= B6_ROADS_MAX:
            break
        way_id = road.get("way_id")
        if way_id in picked_set:
            continue
        selected.append(road)
        picked_set.add(way_id)
    return selected


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

        geometry = element.get("geometry") or []
        roads.append({
            # 可复建道路子图（OPT-P2-03）：保留 OSM way ID 与 WGS84 折线（采样≤80 点防载荷膨胀），
            # 此前只存距离/名称摘要——查询端截掉了后续建图需要的数据。
            "way_id": f"way{element.get('id')}",
            "provider": "osm",
            "geometry": [
                [round(float(pt.get("lon")), 6), round(float(pt.get("lat")), 6)]
                for pt in geometry[:80] if pt.get("lon") is not None and pt.get("lat") is not None
            ],
            "node_count": len(geometry),
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
        # 道路子图身份（OPT-P2-03）：way_id+geometry 可复建，坐标系与提供方如实标注
        "graph": {"provider": "osm", "coordinate_system": "WGS84",
                  "way_ids": [road["way_id"] for road in roads]},
        # B-6 完整道路网：有界路网数组供地图/三维渲染（此前只回 nearest 两条，
        # 抓到的折线全被丢弃）。车辆可通行道路优先（战术价值），余按距离补足；
        # 单条折线 ≤80 点维持 OPT-P2-03 载荷契约，graph.way_ids 保持全量身份。
        "roads": _cap_roads(roads, vehicle_candidates),
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
        "terrain": get_terrain_routed(
            latitude,
            longitude,
            dem_path,
        ),
        "weather": get_weather_routed(
            latitude,
            longitude,
        ),
        "landcover": get_landcover_routed(
            latitude,
            longitude,
        ),
        "water": get_water_sources_routed(
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

    # 来源标注（BE-23）：离线包生效时如实切换，在线路径文案与历史版本一致
    sources = {
        "terrain": "NASA SRTM",
        "weather": "Open-Meteo",
        "landcover": "ESA WorldCover / Microsoft Planetary Computer",
        "water": "OpenStreetMap / Overpass API",
        "road": "OpenStreetMap / Overpass API",
    }
    if modules["terrain"].get("dem_source"):
        sources["terrain"] = "NASA SRTMGL1 v003 / geo-delivery-v2 离线包"
    if modules["landcover"].get("landcover_source"):
        sources["landcover"] = "ESA WorldCover 2021 v200 / geo-delivery-v2 离线包"
    if modules["weather"].get("weather_source"):
        sources["weather"] = modules["weather"]["weather_source"]
    if modules["water"].get("water_candidates_source"):
        sources["water"] = "OSM water_candidates / geo-delivery-v2 离线包（全部 unverified）"

    return {
        "status": status,
        "location": {
            "latitude": latitude,
            "longitude": longitude,
        },
        **modules,
        "sources": sources,
    }
