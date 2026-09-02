from typing import Any, Dict, Optional

from ..pipeline import load_demo_state
from .base import BaseTool, ToolError


class EnvironmentTool(BaseTool):
    name = "get_environment"
    description = "读取指定森林场景的风场、地形、水源和海拔。"
    source = "demo-data"
    def run(self, scene_id: str = "forest-demo-01") -> Dict[str, Any]:
        state = load_demo_state(scene_id)
        scene = state["scene"]
        return {"scene_id": scene_id, "name": scene["name"], "wind_speed": scene["wind_speed"], "wind_direction": scene["wind_direction"], "altitude": scene["altitude"], "terrain": scene["terrain"], "water_sources": scene["water_sources"]}


class FleetStatusTool(BaseTool):
    name = "get_fleet_status"
    description = "读取机群电量、角色、载荷和当前状态。"
    source = "demo-data"
    def run(self, scene_id: str = "forest-demo-01") -> Dict[str, Any]:
        return {"scene_id": scene_id, "fleet": load_demo_state(scene_id)["fleet"]}


class InventoryTool(BaseTool):
    name = "get_inventory"
    description = "读取水、干粉和备用物资库存。"
    source = "demo-data"
    def run(self, scene_id: str = "forest-demo-01") -> Dict[str, Any]:
        return {"scene_id": scene_id, "inventory": load_demo_state(scene_id)["inventory"]}
