#!/usr/bin/env python3
"""Download and package Open-Meteo weather data for the Nanjing delivery."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import geopandas as gpd
import requests


FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
DOCS_URL = "https://open-meteo.com/en/docs"
HISTORICAL_DOCS_URL = "https://open-meteo.com/en/docs/historical-weather-api"
LICENSE_URL = "https://open-meteo.com/en/licence"
TIMEZONE = "Asia/Shanghai"
REPLAY_START = "2026-09-13"
REPLAY_END = "2026-09-15"
DEMO_LATITUDE = 32.0688
DEMO_LONGITUDE = 118.8432
DEMO_POINT_NAME = "紫金山演示报警点"
HOURLY_VARIABLES = (
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def compass(degrees: Any) -> str | None:
    if degrees is None:
        return None
    labels = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
    return labels[int((float(degrees) + 22.5) // 45) % 8]


def wind_to(degrees: Any) -> float | None:
    if degrees is None:
        return None
    return round((float(degrees) + 180.0) % 360.0, 1)


def nanjing_demo_point(boundary_path: Path) -> tuple[float, float, str]:
    boundaries = gpd.read_file(boundary_path).to_crs("EPSG:4326")
    confirmed = boundaries.loc[boundaries["boundary_type"].eq("confirmed_aoi")]
    if len(confirmed) != 1:
        raise ValueError(f"Expected one confirmed_aoi feature, found {len(confirmed)}")
    point = gpd.points_from_xy([DEMO_LONGITUDE], [DEMO_LATITUDE], crs="EPSG:4326")[0]
    if not confirmed.geometry.iloc[0].covers(point):
        raise ValueError("The Zijin Mountain demonstration alarm point is not inside the confirmed Nanjing AOI")
    return DEMO_LATITUDE, DEMO_LONGITUDE, "fixed_zijin_mountain_demonstration_alarm_point"


def request_json(url: str, params: dict[str, Any]) -> tuple[dict[str, Any], str]:
    response = requests.get(url, params=params, timeout=(10, 60))
    response.raise_for_status()
    return response.json(), response.url


def hourly_records(raw: dict[str, Any], source_type: str) -> list[dict[str, Any]]:
    hourly = raw.get("hourly") or {}
    times = hourly.get("time") or []
    records: list[dict[str, Any]] = []
    for index, valid_time in enumerate(times):
        values = {
            name: (hourly.get(name) or [None] * len(times))[index]
            for name in HOURLY_VARIABLES
        }
        wind_from = values["wind_direction_10m"]
        wind_to_deg = wind_to(wind_from)
        missing = [name for name, value in values.items() if value is None]
        records.append(
            {
                "valid_time": valid_time,
                "temperature_2m_c": values["temperature_2m"],
                "relative_humidity_2m_pct": values["relative_humidity_2m"],
                "precipitation_previous_hour_mm": values["precipitation"],
                "wind_speed_10m_m_s": values["wind_speed_10m"],
                "wind_gusts_10m_previous_hour_max_m_s": values["wind_gusts_10m"],
                "wind_from_10m_deg": wind_from,
                "wind_from_10m_compass": compass(wind_from),
                "wind_to_10m_deg": wind_to_deg,
                "wind_to_10m_compass": compass(wind_to_deg),
                "source_type": source_type,
                "missing_fields": ";".join(missing) if missing else None,
            }
        )
    return records


def timestamps_are_hourly(records: list[dict[str, Any]]) -> bool:
    if len(records) < 2:
        return True
    times = [datetime.fromisoformat(row["valid_time"]) for row in records]
    return all((right - left).total_seconds() == 3600 for left, right in zip(times, times[1:]))


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / "data/nanjing/weather"
    qa_dir = root / "qa"
    output.mkdir(parents=True, exist_ok=True)
    qa_dir.mkdir(parents=True, exist_ok=True)
    boundary_path = root / "data/nanjing/srtm/nanjing_srtm_boundaries.geojson"
    latitude, longitude, point_method = nanjing_demo_point(boundary_path)
    fetched_at_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    delivery_date = datetime.now(ZoneInfo(TIMEZONE)).strftime("%Y%m%d")

    common = {
        "latitude": latitude,
        "longitude": longitude,
        "timezone": TIMEZONE,
        "wind_speed_unit": "ms",
        "temperature_unit": "celsius",
        "precipitation_unit": "mm",
        "timeformat": "iso8601",
    }
    forecast_params = {
        **common,
        "current": ",".join(HOURLY_VARIABLES),
        "hourly": ",".join(HOURLY_VARIABLES),
        "forecast_hours": 24,
    }
    archive_params = {
        **common,
        "hourly": ",".join(HOURLY_VARIABLES),
        "start_date": REPLAY_START,
        "end_date": REPLAY_END,
    }

    print("[1/5] Requesting current conditions and 24-hour forecast")
    forecast_raw, forecast_request_url = request_json(FORECAST_URL, forecast_params)
    print("[2/5] Requesting fixed 72-hour historical replay")
    replay_raw, replay_request_url = request_json(ARCHIVE_URL, archive_params)

    paths = {
        "current_raw": output / "weather_current_raw.json",
        "current": output / "weather_current.json",
        "forecast_raw": output / "weather_forecast_raw.json",
        "forecast": output / "weather_forecast.json",
        "replay_raw": output / "weather_replay_raw.json",
        "replay": output / "weather_replay.csv",
        "metadata": output / "weather_metadata.json",
        "manifest": output / "manifest.json",
        "qa_report": qa_dir / "nanjing_weather_qa_report.md",
    }
    write_json(paths["current_raw"], forecast_raw)
    write_json(paths["forecast_raw"], forecast_raw)
    write_json(paths["replay_raw"], replay_raw)

    current_raw = forecast_raw.get("current") or {}
    current_units = forecast_raw.get("current_units") or {}
    valid_time_local = datetime.fromisoformat(current_raw["time"]).replace(tzinfo=ZoneInfo(TIMEZONE))
    fetched_time_utc = datetime.fromisoformat(fetched_at_utc)
    age_minutes_at_fetch = round(
        (fetched_time_utc - valid_time_local.astimezone(timezone.utc)).total_seconds() / 60.0,
        2,
    )
    stale_threshold_minutes = 30
    wind_from_deg = current_raw.get("wind_direction_10m")
    wind_to_deg = wind_to(wind_from_deg)
    current = {
        "dataset_id": f"open_meteo_zijinshan_current_{delivery_date}",
        "region_id": "nanjing",
        "location_name": DEMO_POINT_NAME,
        "location_role": "demonstration_alarm_point_within_nanjing_aoi",
        "request_point": {"latitude": latitude, "longitude": longitude, "crs": "EPSG:4326"},
        "returned_grid": {
            "latitude": forecast_raw.get("latitude"),
            "longitude": forecast_raw.get("longitude"),
            "elevation_m": forecast_raw.get("elevation"),
            "timezone": forecast_raw.get("timezone"),
            "utc_offset_seconds": forecast_raw.get("utc_offset_seconds"),
        },
        "valid_time": current_raw.get("time"),
        "fetched_at_utc": fetched_at_utc,
        "age_minutes_at_fetch": age_minutes_at_fetch,
        "stale_threshold_minutes": stale_threshold_minutes,
        "stale": age_minutes_at_fetch > stale_threshold_minutes,
        "interval_seconds": current_raw.get("interval"),
        "temperature_2m_c": current_raw.get("temperature_2m"),
        "relative_humidity_2m_pct": current_raw.get("relative_humidity_2m"),
        "precipitation_current_interval_mm": current_raw.get("precipitation"),
        "wind_speed_10m_m_s": current_raw.get("wind_speed_10m"),
        "wind_gusts_10m_m_s": current_raw.get("wind_gusts_10m"),
        "wind_from_10m_deg": wind_from_deg,
        "wind_from_10m_compass": compass(wind_from_deg),
        "wind_to_10m_deg": wind_to_deg,
        "wind_to_10m_compass": compass(wind_to_deg),
        "units_from_source": current_units,
        "source": "Open-Meteo Forecast API model output",
        "source_url": FORECAST_URL,
        "license": "CC BY 4.0",
    }
    write_json(paths["current"], current)

    forecast_records = hourly_records(forecast_raw, "forecast_model_output")[:24]
    forecast = {
        "dataset_id": f"open_meteo_zijinshan_forecast_24h_{delivery_date}",
        "region_id": "nanjing",
        "location_name": DEMO_POINT_NAME,
        "location_role": "demonstration_alarm_point_within_nanjing_aoi",
        "request_point": {"latitude": latitude, "longitude": longitude, "crs": "EPSG:4326"},
        "returned_grid": {
            "latitude": forecast_raw.get("latitude"),
            "longitude": forecast_raw.get("longitude"),
            "elevation_m": forecast_raw.get("elevation"),
            "timezone": forecast_raw.get("timezone"),
            "utc_offset_seconds": forecast_raw.get("utc_offset_seconds"),
        },
        "fetched_at_utc": fetched_at_utc,
        "forecast_issued_at": None,
        "source": "Open-Meteo Forecast API model output; best-match model selection",
        "source_url": FORECAST_URL,
        "license": "CC BY 4.0",
        "records": forecast_records,
    }
    write_json(paths["forecast"], forecast)

    replay_records = hourly_records(replay_raw, "historical_model_or_reanalysis_output")
    replay_columns = [
        "valid_time",
        "temperature_2m_c",
        "relative_humidity_2m_pct",
        "precipitation_previous_hour_mm",
        "wind_speed_10m_m_s",
        "wind_gusts_10m_previous_hour_max_m_s",
        "wind_from_10m_deg",
        "wind_from_10m_compass",
        "wind_to_10m_deg",
        "wind_to_10m_compass",
        "source_type",
        "missing_fields",
    ]
    with paths["replay"].open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=replay_columns)
        writer.writeheader()
        writer.writerows(replay_records)

    metadata = {
        "dataset_id": f"open_meteo_zijinshan_weather_delivery_{delivery_date}",
        "region_id": "nanjing",
        "scope": "one fixed demonstration alarm point at Zijin Mountain within the confirmed Nanjing AOI",
        "request_point": {
            "name": DEMO_POINT_NAME,
            "role": "demonstration_alarm_point",
            "latitude": latitude,
            "longitude": longitude,
            "crs": "EPSG:4326",
            "selection_method": point_method,
            "boundary_source": str(boundary_path.relative_to(root)).replace("\\", "/"),
        },
        "forecast_request_url": forecast_request_url,
        "historical_request_url": replay_request_url,
        "fetched_at_utc": fetched_at_utc,
        "forecast_model_selection": "best_match",
        "historical_model_selection": "best_match historical API",
        "replay_period_local": {"start": REPLAY_START, "end": REPLAY_END, "expected_hours": 72},
        "timezone": TIMEZONE,
        "crs": "EPSG:4326",
        "temporal_resolution": "1 hour",
        "recommended_refresh_interval_minutes": 15,
        "stale_threshold_minutes": stale_threshold_minutes,
        "temperature_height": "2 m above ground",
        "humidity_height": "2 m above ground",
        "wind_height": "10 m above ground",
        "wind_direction_convention": "meteorological from-direction, north=0 degrees, clockwise; to=(from+180) mod 360",
        "precipitation_semantics": {
            "current": "sum for the current source interval; interval_seconds retained in weather_current.json",
            "hourly": "sum over the preceding hour",
        },
        "units": {
            "temperature": "degree Celsius",
            "relative_humidity": "percent",
            "precipitation": "millimetre",
            "wind_speed_and_gust": "metre per second",
            "wind_direction": "degree",
        },
        "source": "Open-Meteo Forecast API and Historical Weather API",
        "documentation": [DOCS_URL, HISTORICAL_DOCS_URL],
        "license": "CC BY 4.0",
        "license_url": LICENSE_URL,
        "limitations": [
            "Weather values are model or reanalysis outputs, not an independent weather station observation.",
            "The 72-hour replay is a fixed historical sequence for reproducible simulation and is not a historical forecast verification dataset.",
            "forecast_issued_at is null because the combined best-match response does not provide one authoritative issue time.",
        ],
    }
    write_json(paths["metadata"], metadata)

    print("[3/5] Running weather QA")
    current_required = [
        current["valid_time"],
        current["temperature_2m_c"],
        current["relative_humidity_2m_pct"],
        current["precipitation_current_interval_mm"],
        current["wind_speed_10m_m_s"],
        current["wind_from_10m_deg"],
        current["wind_gusts_10m_m_s"],
    ]
    checks = {
        "current_required_fields_present": all(value is not None for value in current_required),
        "current_not_stale_at_fetch": not current["stale"],
        "forecast_record_count_24": len(forecast_records) == 24,
        "forecast_hourly_continuity": timestamps_are_hourly(forecast_records),
        "replay_record_count_72": len(replay_records) == 72,
        "replay_hourly_continuity": timestamps_are_hourly(replay_records),
        "forecast_no_missing_values": all(row["missing_fields"] is None for row in forecast_records),
        "replay_no_missing_values": all(row["missing_fields"] is None for row in replay_records),
        "wind_to_formula_consistent": all(
            row["wind_from_10m_deg"] is None
            or row["wind_to_10m_deg"] == wind_to(row["wind_from_10m_deg"])
            for row in forecast_records + replay_records
        ),
        "source_units_ms": (forecast_raw.get("hourly_units") or {}).get("wind_speed_10m") == "m/s"
        and (replay_raw.get("hourly_units") or {}).get("wind_speed_10m") == "m/s",
    }
    qa_status = "PASS" if all(checks.values()) else "PARTIAL_PASS"

    qa_lines = [
        "# Nanjing Open-Meteo weather QA report",
        "",
        f"- QA status: **{qa_status}**",
        f"- Request point: `{latitude}, {longitude}` (WGS84)",
        f"- Fetched at UTC: `{fetched_at_utc}`",
        f"- Current valid time: `{current['valid_time']}`",
        f"- Forecast records: {len(forecast_records)}",
        f"- Replay records: {len(replay_records)}",
        f"- Replay period: `{REPLAY_START}` through `{REPLAY_END}` in `{TIMEZONE}`",
        "",
        "## Checks",
        "",
    ]
    qa_lines.extend(f"- {name}: {'PASS' if passed else 'FAIL'}" for name, passed in checks.items())
    qa_lines.extend(
        [
            "",
            "## Interpretation limits",
            "",
            "The current and forecast files contain weather-model output. The fixed replay contains historical model or reanalysis output and must not be described as measurements from a local station.",
            "",
            "The current precipitation interval is retained separately from hourly preceding-hour precipitation. Missing values remain empty rather than being converted to zero.",
            "",
        ]
    )
    paths["qa_report"].write_text("\n".join(qa_lines), encoding="utf-8")

    print("[4/5] Writing weather manifest")
    files = []
    for role, path in paths.items():
        if role == "manifest" or not path.exists():
            continue
        files.append(
            {
                "role": role,
                "path": str(path.relative_to(root)).replace("\\", "/"),
                "size_bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
        )
    manifest = {
        "schema_version": "fire-patrol-weather-manifest-v1",
        "dataset_id": f"Open_Meteo_Zijinshan_Current_Forecast_Replay_{delivery_date}",
        "region_id": "nanjing",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "qa_status": qa_status,
        "source_urls": [FORECAST_URL, ARCHIVE_URL],
        "license": "CC BY 4.0",
        "files": files,
    }
    write_json(paths["manifest"], manifest)
    print("[5/5] Complete")
    print(json.dumps({"qa_status": qa_status, "request_point": [latitude, longitude], "forecast_hours": len(forecast_records), "replay_hours": len(replay_records), "output": str(output)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
