import threading
from typing import Any, Dict, Optional

from ..pipeline import load_demo_state
from ..services.environment_cache import environment_cache
from .base import BaseTool, ToolError


# 紫金山天文台附近的公开演示坐标；真实项目应优先使用影像元数据。
# 紫金山主峰（头陀岭）DEM 实测高点，与 terrain_service 默认值保持一致。
DEFAULT_LATITUDE = 32.0725
DEFAULT_LONGITUDE = 118.8415

# single-flight：冷缓存时前端并发发出多路相同请求，只放行一路抓取，其余等待后读缓存
_inflight_guard = threading.Lock()
_inflight: Dict[str, threading.Event] = {}


class EnvironmentTool(BaseTool):
    name = "get_environment"
    description = "根据火点经纬度查询地形、天气、植被、水源和道路环境信息。"
    source = "SRTM + Open-Meteo + ESA WorldCover + OpenStreetMap"

    def run(
        self,
        scene_id: str = "forest-demo-01",
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        water_radius_m: int = 5000,
        road_radius_m: int = 5000,
        environment_mode: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        mode = (environment_mode or ("auto" if latitude is not None or longitude is not None else "demo")).lower()
        if mode not in {"demo", "real", "auto", "offline"}:
            return self._fallback(scene_id, "invalid_mode", "environment_mode 必须是 demo、real、auto 或 offline")
        if mode == "offline":
            return self._demo(scene_id, metadata={**(metadata or {}), "offline": True, "network": "disabled"})
        if mode == "demo":
            return self._demo(scene_id, metadata=metadata)
        # auto uses the real adapter when coordinates are supplied, otherwise demo.
        if latitude is None and longitude is None and mode == "auto":
            return self._demo(scene_id, metadata=metadata)
        if latitude is None and longitude is None:
            return self._error(scene_id, "coordinates_required", "real 模式必须同时提供 latitude 和 longitude")
        # Keep the heavy geospatial stack out of application startup.
        if latitude is not None or longitude is not None:
            if latitude is None or longitude is None:
                return self._fallback(scene_id, "invalid_coordinates", "latitude 和 longitude 必须同时提供")
            cache_key = ""
            try:
                latitude, longitude = float(latitude), float(longitude)
                if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                    return self._fallback(scene_id, "invalid_coordinates", "经纬度超出有效范围")
                from ..services import environment_service
                fn = environment_service.get_environment
                fn_marker = f"{getattr(getattr(fn, '__code__', None), 'co_filename', '')}:{getattr(getattr(fn, '__code__', None), 'co_firstlineno', '')}:{id(fn)}"
                cache_key = f"{latitude:.6f}:{longitude:.6f}:{water_radius_m}:{road_radius_m}:{fn_marker}"
                cached, stale = environment_cache.get_with_stale(cache_key)
                if cached is not None and not stale:
                    result = dict(cached)
                    if metadata:
                        result["metadata"] = metadata
                    return result
                leader = False
                wait_event: Optional[threading.Event] = None
                with _inflight_guard:
                    existing = _inflight.get(cache_key)
                    if existing is None:
                        _inflight[cache_key] = threading.Event()
                        leader = True
                    else:
                        wait_event = existing
                if not leader:
                    # 另一路相同请求正在抓取：等它落地后读缓存；未落地（失败/超时）再自己抓
                    wait_event.wait(timeout=120)
                    waited, _ = environment_cache.get_with_stale(cache_key)
                    if waited is not None:
                        result = dict(waited)
                        if metadata:
                            result["metadata"] = metadata
                        return result
                try:
                    raw = environment_service.get_environment(
                        latitude, longitude,
                        water_radius_m=water_radius_m,
                        road_radius_m=road_radius_m,
                    )
                    if raw.get("status") == "invalid_input":
                        return self._error(scene_id, "invalid_coordinates", raw.get("error", "经纬度无效"), raw) if mode == "real" else self._fallback(scene_id, "invalid_coordinates", raw.get("error", "经纬度无效"), raw)
                    data = self._normalize(scene_id, raw, mode="real", source="environment_service")
                    data["location"] = raw.get("location", {"latitude": latitude, "longitude": longitude})
                    if metadata:
                        data["metadata"] = metadata
                    # partial（个别数据源失败）不写缓存：空结果不该占住 5 分钟 TTL，下次请求重试数据源
                    if raw.get("status") == "ok":
                        environment_cache.set(cache_key, data)
                    return data
                except Exception as error:
                    stale_value, is_stale = environment_cache.get_with_stale(cache_key)
                    if stale_value is not None and is_stale:
                        stale = dict(stale_value)
                        stale["status"] = "stale"
                        stale["stale"] = True
                        stale["fallback"] = {"code": "environment_unavailable", "message": str(error)}
                        return stale
                    return self._error(scene_id, "environment_unavailable", str(error)) if mode == "real" else self._fallback(scene_id, "environment_unavailable", str(error))
                finally:
                    if leader:
                        with _inflight_guard:
                            done = _inflight.pop(cache_key, None)
                        if done is not None:
                            done.set()
            except Exception as error:
                # 抓取阶段异常已在内层处理；此处兜底参数换算等前置步骤
                return self._error(scene_id, "environment_unavailable", str(error)) if mode == "real" else self._fallback(scene_id, "environment_unavailable", str(error))

    def _demo(self, scene_id: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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
        if metadata:
            data["metadata"] = metadata
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
        # environment_service wraps each provider as {status, data}; water returns
        # the full features collection (capped at 20, distance-sorted) when available.
        weather = cls._module_data(raw, "weather")
        terrain = cls._module_data(raw, "terrain")
        water = cls._module_data(raw, "water")
        road = cls._module_data(raw, "road")
        landcover = cls._module_data(raw, "landcover")
        features = water.get("features")
        if not isinstance(features, list) or not features:
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

    def _error(self, scene_id: str, code: str, message: str, raw: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Return a structured real/partial error without fabricating demo data."""
        return {"scene_id": scene_id, "mode": "real", "status": "error", "source": "environment-service-real", "partial": bool(raw), "error": {"code": code, "message": message}, "raw": raw}

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
