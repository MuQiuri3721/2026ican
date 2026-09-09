"""EXIF GPS 读取与火点定位单测(审计§八 provenance + 架构纪要§四 地理参考)。"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image
from PIL.TiffImagePlugin import IFDRational

from backend.app.tools.exif_gps import read_exif_gps


def make_gps_jpeg(tmp_path, lat_dms, lon_dms, altitude=438):
    img = Image.new("RGB", (64, 48), (40, 100, 40))
    exif = Image.Exif()
    exif[0x8825] = {1: lat_dms[0], 2: tuple(IFDRational(v, 1) for v in lat_dms[1]),
                    3: lon_dms[0], 4: tuple(IFDRational(v, 1) for v in lon_dms[1]),
                    6: IFDRational(altitude, 1)}
    path = tmp_path / "gps.jpg"
    img.save(path, exif=exif)
    return str(path)


def test_read_exif_gps_north_east(tmp_path):
    # (32, 4, 36) = 32°4′36″ = 32 + 4/60 + 36/3600 = 32.0767
    path = make_gps_jpeg(tmp_path, ("N", (32, 4, 36)), ("E", (118, 50, 24)), 438)
    got = read_exif_gps(path)
    assert got["latitude"] == pytest.approx(32.0767, abs=1e-3)
    # (118, 50, 24) = 118°50′24″ = 118 + 50/60 + 24/3600 = 118.84
    assert got["longitude"] == pytest.approx(118.84, abs=1e-3)
    assert got["altitude_m"] == 438.0
    assert got["source"] == "exif-gps"


def test_read_exif_gps_south_west_negates(tmp_path):
    path = make_gps_jpeg(tmp_path, ("S", (32, 4, 36)), ("W", (118, 50, 24)), 200)
    got = read_exif_gps(path)
    assert got["latitude"] == pytest.approx(-32.0767, abs=1e-3)
    assert got["longitude"] == pytest.approx(-118.84, abs=1e-3)


def test_read_exif_gps_missing_or_unreadable(tmp_path):
    assert read_exif_gps(None) is None
    assert read_exif_gps(str(tmp_path / "missing.jpg")) is None
    plain = tmp_path / "plain.jpg"
    plain.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 64)
    assert read_exif_gps(str(plain)) is None  # 无 EXIF → None,调用方回退场景默认位
