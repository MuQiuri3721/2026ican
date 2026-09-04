"""环境/等高线路由（开发者 B 所有）。

环境与地理域的对外入口；实现委托 EnvironmentTool 与 terrain_service。
"""
from fastapi import APIRouter, HTTPException, Query

from ..services.terrain_service import generate_contours
from ..tools.environment import EnvironmentTool

router = APIRouter()


@router.get("/api/environment")
def environment(
    scene_id: str = "forest-demo-01",
    latitude: float | None = None,
    longitude: float | None = None,
    environment_mode: str | None = None,
    water_radius_m: int = Query(3000, gt=0, le=50000),
    road_radius_m: int = Query(3000, gt=0, le=50000),
):
    try:
        return EnvironmentTool().run(scene_id=scene_id, latitude=latitude, longitude=longitude,
                                     environment_mode=environment_mode, water_radius_m=water_radius_m,
                                     road_radius_m=road_radius_m)
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/api/terrain/contours")
def terrain_contours(
    latitude: float = Query(32.1256451, ge=-90, le=90),
    longitude: float = Query(118.9584748, ge=-180, le=180),
    radius_deg: float = Query(0.04, gt=0, le=0.2),
    interval_m: float = Query(20, ge=1, le=500),
    max_points: int = Query(180, ge=20, le=240),
):
    return generate_contours(latitude, longitude, radius_deg, interval_m, max_points)
