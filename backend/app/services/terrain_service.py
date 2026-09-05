"""Local DEM contour generation for the 紫金山 demo area.

The service deliberately returns GeoJSON only (no rendering concerns).  It reads
SRTM HGT through rasterio when available and uses a small marching-squares
implementation so matplotlib is not required by the API process.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

try:
    import rasterio
    from rasterio.windows import Window
except ImportError:  # pragma: no cover - dependency is listed, fallback is API-safe
    rasterio = None
    Window = None

# 紫金山主峰（头陀岭）DEM 实测高点：438 m @ (32.0725N, 118.8415E)。
# 旧默认 (32.1256, 118.9585) 位于山体东北平原，等高线无山形，已替换。
DEFAULT_LATITUDE = 32.0725
DEFAULT_LONGITUDE = 118.8415
DEFAULT_DEM_PATH = Path(__file__).resolve().parents[2] / "N32E118.hgt"
MAX_GRID_SIZE = 240
MAX_FEATURES = 500


def _empty_fallback(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "status": "fallback",
        "source": "demo-data-fallback",
        "features": [],
        "fallback": {"code": code, "message": message},
        **extra,
    }


def _segments_for_cell(values: tuple[float, float, float, float], level: float) -> list[tuple[int, int]]:
    # corners are top-left, top-right, bottom-right, bottom-left; edge ids are
    # top, right, bottom, left.  A saddle is intentionally split into two lines.
    mask = sum((value >= level) << index for index, value in enumerate(values))
    table = {
        1: [(3, 0)], 2: [(0, 1)], 3: [(3, 1)], 4: [(1, 2)], 5: [(3, 2), (0, 1)],
        6: [(0, 2)], 7: [(3, 2)], 8: [(2, 3)], 9: [(0, 2)], 10: [(0, 1), (2, 3)],
        11: [(1, 2)], 12: [(3, 1)], 13: [(0, 1)], 14: [(3, 0)],
    }
    return table.get(mask, [])


def _point(edge: int, x: int, y: int, values: tuple[float, float, float, float], level: float) -> tuple[float, float]:
    edges = ((0, 1, (0, 0), (1, 0)), (1, 2, (1, 0), (1, 1)),
             (2, 3, (1, 1), (0, 1)), (3, 0, (0, 1), (0, 0)))
    a, b, pa, pb = edges[edge]
    denominator = values[b] - values[a]
    ratio = 0.5 if abs(denominator) < 1e-12 else (level - values[a]) / denominator
    ratio = max(0.0, min(1.0, ratio))
    return (x + pa[0] + (pb[0] - pa[0]) * ratio, y + pa[1] + (pb[1] - pa[1]) * ratio)


def _contours(grid: np.ndarray, levels: list[float], lons: np.ndarray, lats: np.ndarray) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    for level in levels:
        segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
        for y in range(grid.shape[0] - 1):
            for x in range(grid.shape[1] - 1):
                values = tuple(float(v) for v in (grid[y, x], grid[y, x + 1], grid[y + 1, x + 1], grid[y + 1, x]))
                for first, second in _segments_for_cell(values, level):
                    segments.append((_point(first, x, y, values, level), _point(second, x, y, values, level)))
        while segments and len(features) < MAX_FEATURES:
            start, end = segments.pop()
            line = [start, end]
            changed = True
            while changed:
                changed = False
                for index, (a, b) in enumerate(segments):
                    if math.dist(line[-1], a) < 1e-7:
                        line.append(b); segments.pop(index); changed = True; break
                    if math.dist(line[-1], b) < 1e-7:
                        line.append(a); segments.pop(index); changed = True; break
                    if math.dist(line[0], b) < 1e-7:
                        line.insert(0, a); segments.pop(index); changed = True; break
                    if math.dist(line[0], a) < 1e-7:
                        line.insert(0, b); segments.pop(index); changed = True; break
            coordinates = [[round(float(lons[int(round(px))]), 6), round(float(lats[int(round(py))]), 6)] for px, py in line]
            # Keep contours valid and compact; duplicate vertices can occur at a saddle.
            if len(coordinates) >= 2 and coordinates[0] != coordinates[-1]:
                features.append({"type": "Feature", "properties": {"elevation_m": round(level, 1)}, "geometry": {"type": "LineString", "coordinates": coordinates}})
    return features


def generate_grid(latitude: float = DEFAULT_LATITUDE, longitude: float = DEFAULT_LONGITUDE,
                  radius_deg: float = 0.04, size: int = 141, dem_path: str | Path | None = None) -> dict[str, Any]:
    """规则高程网格（FE-29 三维地形）：HGT 窗口重采样为 size×size，供前端 three.js 位移地形。"""
    try:
        latitude, longitude = float(latitude), float(longitude)
        radius_deg, size = float(radius_deg), int(size)
    except (TypeError, ValueError) as error:
        return _empty_fallback("invalid_parameters", str(error))
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        return _empty_fallback("invalid_coordinates", "latitude/longitude 超出有效范围")
    if not 0 < radius_deg <= 0.2 or not 40 <= size <= 241:
        return _empty_fallback("invalid_parameters", "radius_deg 或 size 超出允许范围")
    if rasterio is None:
        return _empty_fallback("rasterio_unavailable", "DEM 读取依赖未安装")
    path = Path(dem_path) if dem_path else DEFAULT_DEM_PATH
    try:
        with rasterio.open(path) as dataset:
            row, col = dataset.index(longitude, latitude)
            half = max(2, int(radius_deg / abs(dataset.transform.e) / 2))
            win = min(max(size, 2 * half + 1), 4 * half + 1)
            half = win // 2
            window = Window(col - half, row - half, win, win)
            data = dataset.read(1, window=window, boundless=True, masked=True).astype(float)
            grid = data.filled(np.nan)
            if not np.isfinite(grid).any():
                return _empty_fallback("dem_no_data", "目标区域没有有效 DEM 数据")
            stride = max(1, int(math.ceil(max(grid.shape) / size)))
            grid = grid[::stride, ::stride]
            transform = dataset.window_transform(window)
            xs = transform.c + (np.arange(grid.shape[1]) + 0.5) * transform.a * stride
            ys = transform.f + (np.arange(grid.shape[0]) + 0.5) * transform.e * stride
        valid = grid[np.isfinite(grid)]
        return {"status": "ok", "source": "N32E118.hgt",
                "location": {"latitude": latitude, "longitude": longitude},
                "nx": int(grid.shape[1]), "ny": int(grid.shape[0]),
                "cell_m": round(abs(transform.a) * stride, 1),
                "min_elev": round(float(valid.min()), 1), "max_elev": round(float(valid.max()), 1),
                "lon0": round(float(xs[0]), 6), "lat0": round(float(ys[0]), 6),
                "lon1": round(float(xs[-1]), 6), "lat1": round(float(ys[-1]), 6),
                "elevations": [[round(float(v), 1) if np.isfinite(v) else None for v in row] for row in grid]}
    except (FileNotFoundError, OSError, ValueError, RuntimeError) as error:
        return _empty_fallback("dem_unavailable", str(error), location={"latitude": latitude, "longitude": longitude})


def generate_contours(latitude: float = DEFAULT_LATITUDE, longitude: float = DEFAULT_LONGITUDE,
                      radius_deg: float = 0.04, interval_m: float = 20, max_points: int = 180,
                      dem_path: str | Path | None = None) -> dict[str, Any]:
    """Read a bounded HGT window and return a constrained GeoJSON collection."""
    try:
        latitude, longitude = float(latitude), float(longitude)
        radius_deg, interval_m, max_points = float(radius_deg), float(interval_m), int(max_points)
    except (TypeError, ValueError) as error:
        return _empty_fallback("invalid_parameters", str(error))
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        return _empty_fallback("invalid_coordinates", "latitude/longitude 超出有效范围")
    if not 0 < radius_deg <= 0.2 or not 1 <= interval_m <= 500 or not 20 <= max_points <= MAX_GRID_SIZE:
        return _empty_fallback("invalid_parameters", "radius_deg、interval_m 或 max_points 超出允许范围")
    if rasterio is None:
        return _empty_fallback("rasterio_unavailable", "DEM 读取依赖未安装")
    path = Path(dem_path) if dem_path else DEFAULT_DEM_PATH
    try:
        with rasterio.open(path) as dataset:
            row, col = dataset.index(longitude, latitude)
            half = max(2, int(radius_deg / abs(dataset.transform.e) / 2))
            size = min(max_points, 2 * half + 1)
            half = size // 2
            window = Window(col - half, row - half, size, size)
            data = dataset.read(1, window=window, boundless=True, masked=True).astype(float)
            grid = data.filled(np.nan)
            if not np.isfinite(grid).any():
                return _empty_fallback("dem_no_data", "目标区域没有有效 DEM 数据")
            # Downsample large windows while retaining a regular grid.
            stride = max(1, int(math.ceil(max(grid.shape) / MAX_GRID_SIZE)))
            grid = grid[::stride, ::stride]
            transform = dataset.window_transform(window)
            xs = transform.c + (np.arange(grid.shape[1]) + 0.5) * transform.a * stride
            ys = transform.f + (np.arange(grid.shape[0]) + 0.5) * transform.e * stride
        valid = grid[np.isfinite(grid)]
        low = math.ceil(float(valid.min()) / interval_m) * interval_m
        high = math.floor(float(valid.max()) / interval_m) * interval_m
        levels = [low + i * interval_m for i in range(int((high - low) / interval_m) + 1)] if high >= low else []
        features = _contours(grid, levels, xs, ys)
        return {"type": "FeatureCollection", "status": "ok", "source": "N32E118.hgt", "location": {"latitude": latitude, "longitude": longitude}, "bounds": {"radius_deg": radius_deg}, "interval_m": interval_m, "features": features[:MAX_FEATURES]}
    except (FileNotFoundError, OSError, ValueError, RuntimeError) as error:
        return _empty_fallback("dem_unavailable", str(error), location={"latitude": latitude, "longitude": longitude})
