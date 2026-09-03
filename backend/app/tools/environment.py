from typing import Any, Dict, Optional

from ..pipeline import load_demo_state
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
        water_radius_m: int = 3000,
        road_radius_m: int = 3000,
    ) -> Dict[str, Any]:
        # Keep the heavy geospatial stack out of application startup.
        if latitude is not None or longitude is not None:
            if latitude is None or longitude is None:
                return self._fallback(scene_id, "invalid_coordinates", "latitude 和 longitude 必须同时提供")
            try:
                latitude, longitude = float(latitude), float(longitude)
                if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                    return self._fallback(scene_id, "invalid_coordinates", "经纬度超出有效范围")
                from ..services import environment_service
                raw = environment_service.get_environment(
                    latitude, longitude,
                    water_radius_m=water_radius_m,
                    road_radius_m=road_radius_m,
                )
                if raw.get("status") == "invalid_input":
                    return self._fallback(scene_id, "invalid_coordinates", raw.get("error", "经纬度无效"), raw)
                return self._normalize(scene_id, raw, mode="real", source="environment_service")
            except Exception as error:
                return self._fallback(scene_id, "environment_unavailable", str(error))

        try:
            state = load_demo_state(scene_id)
        except ValueError as error:
            raise ToolError("scene_not_found", str(error), {"scene_id": scene_id}) from error
        scene = state["scene"]
        data = {
            "scene_id": scene_id, "name": scene["name"], "mode": "demo", "status": "ok", "source": "demo-data",
            "wind_speed": scene["wind_speed"], "wind_direction": scene["wind_direction"],
            "altitude": scene["altitude"], "terrain": scene["terrain"],
            "water_sources": scene["water_sources"], "nearest_water": scene["water_sources"][0] if scene["water_sources"] else None,
            "preferred_water": scene["water_sources"][0] if scene["water_sources"] else None,
            "road_context": None, "landcover": None,
        }
        data["raw"] = dict(data)
        return data

    @staticmethod
    def _module_data(raw: Dict[str, Any], name: str) -> Dict[str, Any]:
        module = raw.get(name) or {}
        if not isinstance(module, dict):
            return {}
        data = module.get("data", module)
        return data if isinstance(data, dict) else {}

    @classmethod
    def _normalize(cls, scene_id: str, raw: Dict[str, Any], mode: str, source: str) -> Dict[str, Any]:
        # environment_service wraps each provider as {status, data}; water itself
        # returns nearest/preferred rather than a features collection.
        weather = cls._module_data(raw, "weather")
        terrain = cls._module_data(raw, "terrain")
        water = cls._module_data(raw, "water")
        road = cls._module_data(raw, "road")
        landcover = cls._module_data(raw, "landcover")
        features = water.get("features")
        if not isinstance(features, list):
            features = [item for item in (water.get("nearest"), water.get("preferred")) if item]
        status = raw.get("status") or mode
        return {
            "scene_id": scene_id, "mode": mode, "status": status, "source": source,
            "wind_speed": weather.get("wind_speed_m_s"),
            "wind_direction": weather.get("wind_to_direction"),
            "wind_direction_deg": weather.get("wind_to_deg"),
            "altitude": terrain.get("elevation_m"), "terrain": terrain,
            "water_sources": features,
            "nearest_water": water.get("nearest"),
            "preferred_water": water.get("preferred"),
            "road_context": road, "landcover": landcover, "raw": raw,
        }

    def _fallback(self, scene_id: str, code: str, message: str, raw: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        try:
            state = load_demo_state(scene_id)
            scene = state["scene"]
            data = {
                "scene_id": scene_id, "mode": "demo-fallback", "status": "error", "source": "demo-data-fallback",
                "wind_speed": scene["wind_speed"], "wind_direction": scene["wind_direction"],
                "altitude": scene["altitude"], "terrain": scene["terrain"],
                "water_sources": scene["water_sources"], "nearest_water": scene["water_sources"][0] if scene["water_sources"] else None,
                "preferred_water": scene["water_sources"][0] if scene["water_sources"] else None,
                "road_context": None, "landcover": None,
                "fallback": {"code": code, "message": message}, "raw": raw,
            }
            return data
        except ValueError as error:
            raise ToolError("scene_not_found", str(error), {"scene_id": scene_id}) from error


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
