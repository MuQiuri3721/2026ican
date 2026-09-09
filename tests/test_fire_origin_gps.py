"""指定坐标(操作员经纬度)火点前置定位单测。

覆盖 api-contract §5.1/§5.2 的 latitude/longitude 语义：显式坐标 > EXIF > 场景默认、
紫霞湖基地正向锚定数学、50km 合理护栏与来源标注(operator-gps/exif-gps)。
"""
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image
from PIL.TiffImagePlugin import IFDRational

from backend.app.domain.scenarios import ZIXIAHU_BASE_GPS, fleet_average_position
from backend.app.pipeline import load_demo_state


def _make_gps_jpeg(tmp_path, lat_dms, lon_dms):
    img = Image.new("RGB", (64, 48), (40, 100, 40))
    exif = Image.Exif()
    exif[0x8825] = {1: lat_dms[0], 2: tuple(IFDRational(v, 1) for v in lat_dms[1]),
                    3: lon_dms[0], 4: tuple(IFDRational(v, 1) for v in lon_dms[1])}
    path = tmp_path / "gps.jpg"
    img.save(path, exif=exif)
    return str(path)


def _expected_origin(lat: float, lng: float) -> dict:
    base_xy = fleet_average_position()
    base_lat = ZIXIAHU_BASE_GPS["latitude"]
    base_lng = ZIXIAHU_BASE_GPS["longitude"]
    m_lat = 111320.0
    m_lng = m_lat * math.cos(math.radians(base_lat))
    return {
        "x": round(base_xy["x"] + (lng - base_lng) * m_lng, 1),
        "y": round(base_xy["y"] + (lat - base_lat) * m_lat, 1),
    }


def _analyze_scene(client, **kwargs) -> dict:
    payload = {"scene_id": "forest-demo-01", "use_vlm": False, "environment_mode": "offline"}
    payload.update(kwargs)
    response = client.post("/api/analyze", json=payload, timeout=300)
    assert response.status_code == 200, response.text
    envelope = response.json()
    client.post(f"/api/tasks/{envelope['analysis_id']}/approval", json={"action": "terminate", "reason": "测试清理"})
    return envelope["result"]["scene"]


def test_operator_coordinates_move_fire_origin():
    """指定坐标 → 火点 GPS 锚定到指定位置，相对框架原点正向迁移（管线前）。"""
    from fastapi.testclient import TestClient

    from backend.app.main import app

    lat, lng = 32.10, 118.90
    with TestClient(app) as client:
        scene = _analyze_scene(client, latitude=lat, longitude=lng)
    assert scene["fire_origin_source"] == "operator-gps"
    assert scene["fire_origin_gps"] == {"latitude": lat, "longitude": lng}
    expected = _expected_origin(lat, lng)
    assert scene["fire_origin"]["x"] == pytest.approx(expected["x"], abs=0.2)
    assert scene["fire_origin"]["y"] == pytest.approx(expected["y"], abs=0.2)


def test_operator_coordinates_override_exif(tmp_path):
    """显式坐标优先级高于照片 EXIF 拍摄位（api-contract：显式坐标 > EXIF > 场景默认）。"""
    from fastapi.testclient import TestClient

    from backend.app.main import app

    jpeg = _make_gps_jpeg(tmp_path, ("N", (32, 4, 36)), ("E", (118, 50, 24)))
    payload = Path(jpeg).read_bytes()
    lat, lng = 32.09, 118.88
    with TestClient(app) as client:
        response = client.post(
            "/api/analyze/upload",
            files={"file": ("gps.jpg", payload, "image/jpeg")},
            data={"latitude": str(lat), "longitude": str(lng), "environment_mode": "offline"},
            timeout=300,
        )
        assert response.status_code == 200, response.text
        envelope = response.json()
        client.post(f"/api/tasks/{envelope['analysis_id']}/approval", json={"action": "terminate", "reason": "测试清理"})
        scene = envelope["result"]["scene"]
    assert scene["fire_origin_source"] == "operator-gps"
    assert scene["fire_origin_gps"] == {"latitude": lat, "longitude": lng}


def test_exif_only_upload_keeps_exif_source(tmp_path):
    """无显式坐标时 EXIF 仍生效（回归既有行为）。"""
    from fastapi.testclient import TestClient

    from backend.app.main import app

    jpeg = _make_gps_jpeg(tmp_path, ("N", (32, 4, 36)), ("E", (118, 50, 24)))
    payload = Path(jpeg).read_bytes()
    with TestClient(app) as client:
        response = client.post(
            "/api/analyze/upload",
            files={"file": ("gps.jpg", payload, "image/jpeg")},
            data={"environment_mode": "offline"},
            timeout=300,
        )
        assert response.status_code == 200, response.text
        envelope = response.json()
        client.post(f"/api/tasks/{envelope['analysis_id']}/approval", json={"action": "terminate", "reason": "测试清理"})
        scene = envelope["result"]["scene"]
    assert scene["fire_origin_source"] == "exif-gps"
    assert scene["fire_origin_gps"]["latitude"] == pytest.approx(32.0767, abs=1e-3)


def test_far_coordinates_keep_default_frame_but_record_gps():
    """超出基地 50km 护栏：GPS 锚点与来源仍记录，相对框架保持场景默认位（防框架爆逸）。"""
    from fastapi.testclient import TestClient

    from backend.app.main import app

    lat, lng = 33.50, 118.90
    with TestClient(app) as client:
        scene = _analyze_scene(client, latitude=lat, longitude=lng)
    assert scene["fire_origin_source"] == "operator-gps"
    assert scene["fire_origin_gps"] == {"latitude": lat, "longitude": lng}
    default = load_demo_state("forest-demo-01")["scene"]["fire_origin"]
    assert scene["fire_origin"] == default
