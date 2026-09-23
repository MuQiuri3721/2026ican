# Nanjing Open-Meteo weather QA report

- QA status: **PASS**
- Request point: `32.0688, 118.8432` (WGS84)
- Fetched at UTC: `2026-09-23T06:04:13+00:00`
- Current valid time: `2026-09-23T14:00`
- Forecast records: 24
- Replay records: 72
- Replay period: `2026-09-13` through `2026-09-15` in `Asia/Shanghai`

## Checks

- current_required_fields_present: PASS
- current_not_stale_at_fetch: PASS
- forecast_record_count_24: PASS
- forecast_hourly_continuity: PASS
- replay_record_count_72: PASS
- replay_hourly_continuity: PASS
- forecast_no_missing_values: PASS
- replay_no_missing_values: PASS
- wind_to_formula_consistent: PASS
- source_units_ms: PASS

## Interpretation limits

The current and forecast files contain weather-model output. The fixed replay contains historical model or reanalysis output and must not be described as measurements from a local station.

The current precipitation interval is retained separately from hourly preceding-hour precipitation. Missing values remain empty rather than being converted to zero.
