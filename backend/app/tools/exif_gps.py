"""EXIF GPS 读取：真实无人机照片自带拍摄位置,火点自动定位到拍摄处。

真实航拍无人机的照片固件会写入 GPS IFD(DJI/大疆等均如此)。平台读取后:
- 有显式坐标(表单 latitude/longitude)→ 以显式为准;
- 无显式坐标 → 以 EXIF GPS 作为火点位置(fire_center / fire_origin_gps),
  真实照片即携带真实地理参考,不再固定在场景默认位。

仅依赖 Pillow(读取);无 EXIF/无 GPS IFD → None,调用方回退场景默认位。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional


def _dms_to_deg(dms) -> Optional[float]:
    """EXIF GPS 的度/分/秒(IFDRational 或数值)→ 十进制度。"""
    try:
        values = [float(v) for v in dms]
        if len(values) != 3:
            return None
        return values[0] + values[1] / 60 + values[2] / 3600
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def read_exif_gps(path: str) -> Optional[dict[str, Any]]:
    """读取 JPEG 的 EXIF GPS,返回 {"latitude", "longitude", "altitude"} 或 None。"""
    if not path or not Path(path).exists():
        return None
    try:
        from PIL import Image
        with Image.open(path) as img:
            exif = img.getexif()
    except Exception:
        return None
    if not exif:
        return None
    gps_ifd = exif.get_ifd(0x8825)  # GPSInfo
    if not gps_ifd:
        return None

    lat_ref = str(gps_ifd.get(1, "N")).upper()
    lat = _dms_to_deg(gps_ifd.get(2))
    lon_ref = str(gps_ifd.get(3, "E")).upper()
    lon = _dms_to_deg(gps_ifd.get(4))
    if lat is None or lon is None:
        return None
    if lat_ref == "S":
        lat = -lat
    if lon_ref == "W":
        lon = -lon
    altitude = gps_ifd.get(6)
    result: dict[str, Any] = {"latitude": round(lat, 6), "longitude": round(lon, 6), "source": "exif-gps"}
    try:
        if altitude is not None:
            result["altitude_m"] = round(float(altitude), 1)
    except (TypeError, ValueError):
        pass
    return result
