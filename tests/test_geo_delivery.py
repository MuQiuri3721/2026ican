"""BE-52：离线地理数据包（geo-delivery-v2）接入测试。

GEO_DATA_ROOT 未配置时环境服务保持纯在线行为（回归保护）；
配置后南京范围内地形/地表覆盖走离线成果、范围外自动回退。
交付包为未跟踪大文件（115MB，.gitignore 已排除），不在本机时整文件 skip。
"""
from pathlib import Path

import pytest

pytest.importorskip("rasterio")

from backend.app.services import environment_service as env_svc

# 版本化目录名；交付包升级（v1.1+）时同步更新此常量
DELIVERY_ROOT = Path(__file__).resolve().parents[1] / "geo-delivery-v2-public-v1.0-20260922"

pytestmark = pytest.mark.skipif(
    not (DELIVERY_ROOT / "data").exists(),
    reason="geo-delivery-v2 包不在本机（未跟踪大文件，仅队内机器可跑）",
)

ZJS_LAT, ZJS_LON = 32.0725, 118.8415  # 紫金山主峰（SK-1 实测 438m）
BJ_LAT, BJ_LON = 39.9, 116.4  # 北京：交付包与 N32E118.hgt 双双不可覆盖


@pytest.fixture()
def geo_root(monkeypatch):
    monkeypatch.setenv("GEO_DATA_ROOT", str(DELIVERY_ROOT))
    monkeypatch.delenv("GEO_DATA_MODE", raising=False)
    return DELIVERY_ROOT


def test_mode_defaults_to_auto_when_root_set(geo_root):
    assert env_svc.geo_data_root() == geo_root
    assert env_svc.geo_data_mode() == "auto"
    assert env_svc.offline_geo_file("dem") is not None


def test_mode_live_when_unset(monkeypatch):
    monkeypatch.delenv("GEO_DATA_ROOT", raising=False)
    monkeypatch.delenv("GEO_DATA_MODE", raising=False)
    assert env_svc.geo_data_mode() == "live"
    assert env_svc.geo_data_root() is None
    assert env_svc.offline_geo_file("dem") is None


def test_terrain_offline_main_peak_matches_hgt_baseline(geo_root):
    """紫金山主峰：交付 DEM 437m vs SK-1 HGT 实测 438m，容差 3m。"""
    result = env_svc.get_terrain_routed(ZJS_LAT, ZJS_LON, env_svc.DEFAULT_DEM_PATH)
    assert result["status"] == "ok"
    assert result["dem_source"].startswith("geo-delivery-v2")
    assert 430 <= result["elevation_m"] <= 445
    assert 0 <= result["slope_deg"] <= 90
    # 主峰顶坡度≈0 → 下坡方向为 None 属正确语义
    if result["slope_deg"] < 0.1:
        assert result["downslope_direction"] is None


def test_landcover_offline_same_shape_as_live(geo_root):
    result = env_svc.get_landcover_routed(ZJS_LAT, ZJS_LON)
    assert result["status"] == "ok"
    assert result["landcover_source"].startswith("geo-delivery-v2")
    assert 0.0 <= result["burnable_ratio"] <= 1.0
    assert isinstance(result["fuel_possible"], bool)
    assert result["center_class"] in set(env_svc.WORLD_COVER_CLASSES.values())


def test_auto_mode_falls_back_to_live_out_of_coverage(geo_root):
    """北京坐标：离线包不覆盖 → auto 回退在线 HGT → HGT 也不覆盖（错误文案可区分）。"""
    result = env_svc.get_terrain_routed(BJ_LAT, BJ_LON, env_svc.DEFAULT_DEM_PATH)
    assert result["status"] == "error"
    assert "离线" not in result["error"], "auto 模式必须回退到在线/HGT 路径"
    assert "覆盖范围" in result["error"]


def test_offline_mode_never_falls_back(geo_root, monkeypatch):
    """offline 模式：范围外不得悄悄回退在线（演示断网兜底语义）。"""
    monkeypatch.setenv("GEO_DATA_MODE", "offline")
    result = env_svc.get_terrain_routed(BJ_LAT, BJ_LON, env_svc.DEFAULT_DEM_PATH)
    assert result["status"] == "error"
    assert "离线" in result["error"]


def test_live_default_unchanged(monkeypatch):
    """未配置 GEO_DATA_ROOT：路由直通在线/HGT 路径，无离线标记（回归保护）。"""
    monkeypatch.delenv("GEO_DATA_ROOT", raising=False)
    monkeypatch.delenv("GEO_DATA_MODE", raising=False)
    result = env_svc.get_terrain_routed(ZJS_LAT, ZJS_LON, env_svc.DEFAULT_DEM_PATH)
    assert result["status"] == "ok"
    assert "dem_source" not in result


def test_weather_offline_shape(geo_root):
    """离线天气：与在线版逐键同形 + 留档来源/stale 诚实标注。"""
    result = env_svc.get_weather_routed(ZJS_LAT, ZJS_LON)
    assert result["status"] == "ok"
    assert result["weather_source"].startswith("geo-delivery-v2")
    for key in ("time", "temperature_c", "relative_humidity_pct",
                "precipitation_mm", "wind_speed_m_s", "wind_from_deg",
                "wind_from_direction", "wind_gust_m_s", "timezone"):
        assert key in result
    assert result["timezone"] == "Asia/Shanghai"


def test_weather_auto_out_of_city_falls_back_to_live(geo_root, monkeypatch):
    monkeypatch.setattr(env_svc, "get_weather", lambda lat, lon: {"temperature_c": 1})
    result = env_svc.get_weather_routed(39.9, 116.4)  # 城市 bbox 外 → 回退在线
    assert result["temperature_c"] == 1
    assert "weather_source" not in result


def test_weather_offline_mode_serves_out_of_city(geo_root, monkeypatch):
    monkeypatch.setenv("GEO_DATA_MODE", "offline")
    result = env_svc.get_weather_routed(39.9, 116.4)  # offline 语义：范围内外都供包
    assert result["weather_source"].startswith("geo-delivery-v2")


def test_water_candidates_offline(geo_root):
    result = env_svc.get_water_sources_routed(ZJS_LAT, ZJS_LON, 5000)
    assert result["status"] == "ok"
    assert result["water_candidates_source"].startswith("geo-delivery-v2")
    # 与在线版同契约：feature_count=半径内全量，features 截断 20 条供打点
    assert result["feature_count"] >= 1
    assert len(result["features"]) <= 20
    distances = [item["distance_m"] for item in result["features"]]
    assert distances == sorted(distances)
    for item in result["features"]:
        assert item["verification_status"] == "unverified"  # 地理存在 ≠ 可取水
        assert item["provider"].endswith("geo-delivery-v2")
        assert item["osm_id"]


def test_water_auto_falls_back_when_offline_missing(geo_root, monkeypatch):
    monkeypatch.setattr(env_svc, "get_water_sources",
                        lambda lat, lon, r: {"found": False, "probe": True})
    result = env_svc.get_water_sources_routed(ZJS_LAT, ZJS_LON, 1)  # 半径 1m 无候选 → 回退
    assert result.get("probe") is True


def test_geo_overview_endpoint(geo_root):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.app.routes import environment_routes

    app = FastAPI()
    app.include_router(environment_routes.router)
    client = TestClient(app)
    resp = client.get("/api/geo/overview")
    assert resp.status_code == 200
    features = resp.json()["features"]
    assert {f["properties"]["name"] for f in features} == {
        "云台山", "宁镇丘陵东段", "宜溧山地", "环太湖丘陵",
    }
    assert all(f["properties"]["official_boundary"] is False for f in features)


def test_geo_overview_endpoint_404_without_root(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.app.routes import environment_routes

    monkeypatch.delenv("GEO_DATA_ROOT", raising=False)
    app = FastAPI()
    app.include_router(environment_routes.router)
    client = TestClient(app)
    assert client.get("/api/geo/overview").status_code == 404


def test_water_offline_mode_keeps_empty_without_fallback(geo_root, monkeypatch):
    monkeypatch.setenv("GEO_DATA_MODE", "offline")
    monkeypatch.setattr(env_svc, "get_water_sources", lambda lat, lon, r: {"probe": "live"})
    result = env_svc.get_water_sources_routed(ZJS_LAT, ZJS_LON, 1)  # 半径 1m 无候选
    assert result["found"] is False
    assert "probe" not in result  # offline 不悄悄回退在线
