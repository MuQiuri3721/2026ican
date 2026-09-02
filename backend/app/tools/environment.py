from typing import Any, Dict

from ..pipeline import load_demo_state


class EnvironmentTool:
    name = "get_environment"

    def run(self, scene_id: str) -> Dict[str, Any]:
        state = load_demo_state(scene_id)
        scene = state["scene"]
        return {"scene_id": scene_id, "name": scene["name"], "wind_speed": scene["wind_speed"], "wind_direction": scene["wind_direction"], "altitude": scene["altitude"], "terrain": scene["terrain"], "water_sources": scene["water_sources"]}


class FleetStatusTool:
    name = "get_fleet_status"

    def run(self, scene_id: str = "forest-demo-01") -> Dict[str, Any]:
        return {"scene_id": scene_id, "fleet": load_demo_state(scene_id)["fleet"]}


class InventoryTool:
    name = "get_inventory"

    def run(self, scene_id: str = "forest-demo-01") -> Dict[str, Any]:
        return {"scene_id": scene_id, "inventory": load_demo_state(scene_id)["inventory"]}
