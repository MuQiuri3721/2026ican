"""环境/等高线路由（开发者 B 所有）。

环境与地理域的对外入口；实现委托 EnvironmentTool 与 terrain_service。
"""
import json

from fastapi import APIRouter, HTTPException, Query

from ..services import environment_service
from ..services.terrain_service import generate_contours, generate_grid
from ..tools.environment import EnvironmentTool

router = APIRouter()


@router.get("/api/environment")
def environment(
    scene_id: str = "forest-demo-01",
    latitude: float | None = None,
    longitude: float | None = None,
    environment_mode: str | None = None,
    water_radius_m: int = Query(5000, gt=0, le=50000),
    road_radius_m: int = Query(5000, gt=0, le=50000),
):
    try:
        return EnvironmentTool().run(scene_id=scene_id, latitude=latitude, longitude=longitude,
                                     environment_mode=environment_mode, water_radius_m=water_radius_m,
                                     road_radius_m=road_radius_m)
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/api/terrain/grid")
def terrain_grid(latitude: float = 32.0725, longitude: float = 118.8415, radius_deg: float = 0.04, size: int = 141):
    """规则高程网格（FE-29 三维地形）：HGT 窗口重采样 size×size。"""
    return generate_grid(latitude=latitude, longitude=longitude, radius_deg=radius_deg, size=size)


@router.get("/api/terrain/contours")
def terrain_contours(
    latitude: float = Query(32.0725, ge=-90, le=90),
    longitude: float = Query(118.8415, ge=-180, le=180),
    radius_deg: float = Query(0.04, gt=0, le=0.2),
    interval_m: float = Query(20, ge=1, le=500),
    max_points: int = Query(180, ge=20, le=240),
):
    return generate_contours(latitude, longitude, radius_deg, interval_m, max_points)


@router.get("/api/geo/overview")
def geo_overview():
    """geo-delivery-v2 公开区域索引（BE-52 第三期）：4 个规划展示区多边形。

    仅在 .env 配置了 GEO_DATA_ROOT 时可用；返回 areas_public.geojson
    （项目派生规划展示区，不含天地图行政边界——授权仅限地图可视化，不入公开仓库）。
    """
    root = environment_service.geo_data_root()
    if root is None:
        raise HTTPException(status_code=404, detail="GEO_DATA_ROOT 未配置，离线地理数据不可用")
    public_index = root / "data" / "overview" / "areas_public.geojson"
    if not public_index.is_file():
        raise HTTPException(status_code=404, detail="交付包缺少 data/overview/areas_public.geojson")
    return json.loads(public_index.read_text(encoding="utf-8"))
