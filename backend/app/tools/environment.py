from typing import Any, Dict, Optional

from ..pipeline import load_demo_state
from ..services.environment_service import get_environment
from .base import BaseTool, ToolError


class EnvironmentTool(BaseTool):
    name = "get_environment"
    description = "根据火点经纬度查询地形、天气、植被、水源和道路环境信息。"
    source = "SRTM + Open-Meteo + ESA WorldCover + OpenStreetMap"

    def run(
        self,
        scene_id: str = "forest-demo-01",
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
    ) -> Dict[str, Any]:

        # 有经纬度时使用真实环境数据
        if latitude is not None and longitude is not None:
            result = get_environment(latitude, longitude)
            return {
                "scene_id": scene_id,
                **result,
            }

        # 未传经纬度时保留原 Demo 数据，避免影响现有流程
        try:
            state = load_demo_state(scene_id)
        except ValueError as error:
            raise ToolError(
                "scene_not_found",
                str(error),
                {"scene_id": scene_id},
            ) from error

        scene = state["scene"]

        return {
            "scene_id": scene_id,
            "name": scene["name"],
            "wind_speed": scene["wind_speed"],
            "wind_direction": scene["wind_direction"],
            "altitude": scene["altitude"],
            "terrain": scene["terrain"],
            "water_sources": scene["water_sources"],
        }


class FleetStatusTool(BaseTool):
    name = "get_fleet_status"
    description = "读取机群电量、角色、载荷和当前状态。"
    source = "demo-data"

    def run(
        self,
        scene_id: str = "forest-demo-01",
    ) -> Dict[str, Any]:
        return {
            "scene_id": scene_id,
            "fleet": load_demo_state(scene_id)["fleet"],
        }


class InventoryTool(BaseTool):
    name = "get_inventory"
    description = "读取水、干粉和备用物资库存。"
    source = "demo-data"

    def run(
        self,
        scene_id: str = "forest-demo-01",
    ) -> Dict[str, Any]:
        return {
            "scene_id": scene_id,
            "inventory": load_demo_state(scene_id)["inventory"],
        }
