"""按文档优化项测试（实现差异审计§六.3 位置变化、§八 输入 hash 溯源、§九 轮次动作展示）。

- analyze_visual_trend / analyze_frame_sequence：帧序列火点位置变化（center_delta_m）
- create_and_run：input_provenance 输入文件 hash（SHA-256 前 16 位）
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.tools.core import analyze_frame_sequence, analyze_visual_trend  # noqa: E402
from backend.app.services.analysis_service import _file_sha16  # noqa: E402


def test_visual_trend_reports_center_movement():
    rows = [
        {"fire_area_m2": 100, "fire_center": {"x": 118.78, "y": 32.04}},
        {"fire_area_m2": 130, "fire_center": {"x": 118.782, "y": 32.041}},
        {"fire_area_m2": 150, "fire_center": {"x": 118.785, "y": 32.043}},
    ]
    trend = analyze_visual_trend(rows)
    assert trend["status"] == "ok" and trend["trend"] == "growing"
    assert trend["center_delta_m"] > 400  # 约 0.005°/0.003° 位移 → 数百米
    assert trend["first_center"] == {"x": 118.78, "y": 32.04}
    assert trend["last_center"] == {"x": 118.785, "y": 32.043}


def test_visual_trend_without_centers_omits_movement():
    trend = analyze_visual_trend([{"fire_area_m2": 100}, {"fire_area_m2": 120}])
    assert trend["status"] == "ok"
    assert "center_delta_m" not in trend


def test_frame_sequence_carries_fire_center(tmp_path, monkeypatch):
    import backend.app.tools.core as core

    def fake_detect(image_name="", image_path=None, **_):
        return {"fire_area_m2": 100.0, "smoke_area_m2": 200.0,
                "fire_center": {"x": 118.78, "y": 32.04}, "confidence": 0.9}

    monkeypatch.setattr(core, "detect_fire", fake_detect)
    result = core.analyze_frame_sequence([str(tmp_path / "a.jpg"), str(tmp_path / "b.jpg")])
    assert result["frame_count"] == 2
    assert result["frames"][0]["fire_center"] == {"x": 118.78, "y": 32.04}
    assert result["trend"]["center_delta_m"] is not None or "center_delta_m" not in result["trend"]


def test_file_sha16_matches_known_vector(tmp_path):
    target = tmp_path / "frame.jpg"
    target.write_bytes(b"hello world")
    import hashlib
    expected = hashlib.sha256(b"hello world").hexdigest()[:16]
    assert _file_sha16(str(target)) == expected
    assert _file_sha16(str(tmp_path / "missing.jpg")) is None
    assert _file_sha16(None) is None


def test_create_and_run_stamps_input_provenance(tmp_path):
    """上传研判后信封必须带输入文件 hash（审计§八 provenance）。"""
    from fastapi.testclient import TestClient

    from backend.app.main import app

    image = tmp_path / "probe.jpg"
    import hashlib
    payload = b"\xff\xd8\xff\xe0" + b"\x00" * 128
    image.write_bytes(payload)
    expected = hashlib.sha256(payload).hexdigest()[:16]

    with TestClient(app) as client:
        response = client.post(
            "/api/analyze/upload",
            files={"file": ("probe.jpg", payload, "image/jpeg")},
            data={"use_vlm": "false", "environment_mode": "offline"},
            timeout=300,
        )
    assert response.status_code == 200
    envelope = response.json()
    provenance = (envelope.get("result") or {}).get("input_provenance") or {}
    assert provenance.get("image_sha256_16") == expected
    assert provenance.get("image_name") == "probe.jpg"
    # 清理：测试任务立即终止释放资源锁
    aid = envelope.get("analysis_id")
    client.post(f"/api/tasks/{aid}/approval", json={"action": "terminate", "reason": "测试清理"})


# ---------- 架构纪要对照（docs/架构职责划分纪要.md） ----------

def test_fire_metrics_reports_image_ratio():
    """纪要§二：PWM-YOLO 输出火焰/烟雾在图像中的占比。"""
    from backend.app.tools.core import calculate_fire_metrics

    metrics = calculate_fire_metrics(
        [{"class_name": "fire", "box": [0, 0, 10, 10]},
         {"class_name": "smoke", "box": [0, 0, 20, 10]}],
        image_width=100, image_height=100,
    )
    assert metrics["fire_ratio"] == 0.01
    assert metrics["smoke_ratio"] == 0.02


def test_environment_surfaces_temperature_humidity_precipitation():
    """纪要§四：地理环境信息模块向决策层提供温度、湿度、降水。"""
    from backend.app.tools.environment import EnvironmentTool

    raw = {"status": "ok",
           "weather": {"status": "ok", "temperature_c": 21.5, "relative_humidity_pct": 63.0,
                       "precipitation_mm": 0.0, "wind_speed_m_s": 3.0,
                       "wind_to_direction": "S", "wind_to_deg": 201.0},
           "terrain": {"status": "ok", "elevation_m": 438.0},
           "water": {"status": "error"}, "road": {"status": "error"}, "landcover": {"status": "error"}}
    data = EnvironmentTool._normalize("forest-demo-01", raw, mode="real", source="test")
    assert data["temperature_c"] == 21.5
    assert data["relative_humidity_pct"] == 63.0
    assert data["precipitation_mm"] == 0.0


def test_report_review_block():
    """纪要§九：复盘档案——初始/最终火势、轮次、版本、审批次数与扑灭判定。"""
    from types import SimpleNamespace

    from backend.app.services.analysis_service import AnalysisService

    item = SimpleNamespace(
        rounds=[
            {"before": {"fire_load_flp": 360.0}, "after": {"fire_load_flp": 300.0}},
            {"before": {"fire_load_flp": 300.0}, "after": {"fire_load_flp": 0.0}},
        ],
        plan_versions=[{"plan_version": 1}, {"plan_version": 2}],
        events=[SimpleNamespace(stage="approval"), SimpleNamespace(stage="approval"), SimpleNamespace(stage="dispatch")],
        result={"fire_assessment": {"fire_load_flp": 360.0}},
        status="completed",
    )
    review = AnalysisService._build_review(item)
    assert review["initial_flp"] == 360.0
    assert review["final_flp"] == 0.0
    assert review["flp_delta"] == -360.0
    assert review["extinguished"] is True
    assert review["round_count"] == 2
    assert review["plan_version_count"] == 2
    assert review["approval_event_count"] == 2
    assert review["status"] == "completed"


# ---------- VLM 视觉评估 → 火情参数映射(FE-46 扩编后续:火随图变) ----------

def test_vlm_visual_assessment_maps_fire_params():
    """真实 VLM 识别成功时,定性视觉判断映射为火情参数(火随图变,地点固定)。"""
    from backend.app.skills.registry import apply_vlm_fire_params

    observation = apply_vlm_fire_params(
        {"fire_area_m2": 1800},
        {"mode": "real",
         "fire_observation": {"visual_scale": "large"},
         "smoke_trend": {"smoke_density": "heavy"}})
    assert observation["fire_area_m2"] == 4500.0
    assert observation["growth_rate"] == 0.7
    assert observation["fire_params_source"] == "demo_mapping"
    assert observation["fire_params_mapping_version"]  # 版本可追踪（OPT-P1-02）
    assert observation["fire_params_scale"] == "large"


def test_vlm_mapping_skipped_when_not_real():
    """限流降级(mode!=real)时保持 fixture 不变——诚实降级,不用降级结果冒充识别。"""
    from backend.app.skills.registry import apply_vlm_fire_params

    observation = apply_vlm_fire_params(
        {"fire_area_m2": 1800},
        {"mode": "fallback", "fire_observation": {"visual_scale": "large"}})
    assert observation["fire_area_m2"] == 1800
    assert "fire_params_source" not in observation


def test_vlm_mapping_skipped_when_no_fire_observed():
    """模型明确没看到火(none_observed/uncertain)时不得驱动火情参数——
    防雾景/水汽误报被映射放大(2026-09-09 webfire 套件发现)。"""
    from backend.app.skills.registry import apply_vlm_fire_params

    for presence in ("none_observed", "uncertain"):
        observation = apply_vlm_fire_params(
            {"fire_area_m2": 1800, "growth_rate": 0.42},
            {"mode": "real",
             "fire_observation": {"fire_presence": presence, "visual_scale": "large"},
             "smoke_trend": {"smoke_density": "heavy"}})
        assert observation["fire_area_m2"] == 1800
        assert observation["growth_rate"] == 0.42
        assert "fire_params_source" not in observation


def test_vlm_smoke_only_mapping_flagged():
    """仅烟(smoke_only)仍映射(烟是林火主要遥感信号),但带 presence 标注供前端展示。"""
    from backend.app.skills.registry import apply_vlm_fire_params

    observation = apply_vlm_fire_params(
        {"fire_area_m2": 1800},
        {"mode": "real",
         "fire_observation": {"fire_presence": "smoke_only", "visual_scale": "medium"},
         "smoke_trend": {"smoke_density": "medium"}})
    assert observation["fire_area_m2"] == 1800.0
    assert observation["growth_rate"] == 0.42
    assert observation["fire_params_source"] == "demo_mapping"
    assert observation["fire_params_presence"] == "smoke_only"


def test_vlm_mapping_tolerates_missing_scale():
    from backend.app.skills.registry import apply_vlm_fire_params

    observation = apply_vlm_fire_params(
        {"fire_area_m2": 1800},
        {"mode": "real", "fire_observation": {"visual_scale": "not_determinable"},
         "smoke_trend": {"smoke_density": "light"}})
    assert observation["fire_area_m2"] == 1800  # 无法判定规模 → 保持原值
    assert observation["growth_rate"] == 0.25   # 烟雾稀疏 → 低增长率仍映射
    assert observation["fire_params_source"] == "demo_mapping"


def test_T17_vlm_mapping_switch_off_keeps_rule_values():
    """T17（OPT-P1-02）：映射关闭时 VLM 标签不得改写任何规则数值；
    开启时来源=demo_mapping 且版本可追踪（模型调用 real 与派生数值分属两源）。"""
    import json as _json

    from backend.app.rules.engine import v1_config
    from backend.app.skills import registry as registry_mod

    payload = {"mode": "real",
               "fire_observation": {"fire_presence": "flame_observed", "visual_scale": "large"},
               "smoke_trend": {"smoke_density": "heavy"}}
    base = {"fire_area_m2": 1800, "growth_rate": 0.42}

    # 关闭：数值原样、无来源标注
    original = v1_config()["vlm_param_mapping"]
    try:
        v1_config()["vlm_param_mapping"] = {**original, "enabled": False}
        off = registry_mod.apply_vlm_fire_params(dict(base), payload)
        assert off["fire_area_m2"] == 1800 and off["growth_rate"] == 0.42
        assert "fire_params_source" not in off
    finally:
        v1_config()["vlm_param_mapping"] = original

    # 开启：映射生效 + demo_mapping 来源 + 版本（模型调用 real ≠ 数值来源）
    on = registry_mod.apply_vlm_fire_params(dict(base), payload)
    assert on["fire_area_m2"] == 4500.0 and on["growth_rate"] == 0.7
    assert on["fire_params_source"] == "demo_mapping"
    assert on["fire_params_mapping_version"] == original.get("version")


def test_P101_vlm_status_fields_and_error_codes():
    """P1-01：回退载荷带本次状态（fallback/skipped）与错误分类码；未配置单列不冒充失败。"""
    import os

    from backend.app.tools.core import analyze_with_vlm

    # 无 Key 无适配器 → skipped（未调用，不冒充失败）
    os.environ.pop("FIRE_VLM_API_KEY", None)
    os.environ.pop("FIRE_VLM_ENDPOINT", None)
    skipped = analyze_with_vlm({"fire_area_m2": 100}, {}, "absent")
    assert skipped.get("status") == "skipped"
    assert skipped["adapter_fallback"]["code"] == "vlm_not_configured"

    # 端点不可达 → fallback + 错误码
    os.environ["FIRE_VLM_ENDPOINT"] = "http://vlm.test/explain"
    result = analyze_with_vlm({}, {}, "absent")
    assert result.get("status") == "fallback"
    assert result["adapter_fallback"]["code"] == "vlm_endpoint_unavailable"
    os.environ.pop("FIRE_VLM_ENDPOINT", None)


def test_T12_environment_values_drive_flp_via_adaptation():
    """T12（OPT-P2-01）：固定面积/风速，仅改变跨档坡度或 WorldCover 燃料类别 →
    实际 FLP 按冻结配置 K 值变化；未知类别回退场景值并标注来源。"""
    from backend.app.tools.core import build_fire_grid, environment_to_rule_inputs

    # 坡度跨档：10°(k1.0) vs 25°(k1.15) → FLP 按配置变化
    flat = build_fire_grid(fire_area_m2=1800, wind_speed=3, slope_deg=10,
                           fuel_type="general_forest", intensity=2)
    steep = build_fire_grid(fire_area_m2=1800, wind_speed=3, slope_deg=25,
                            fuel_type="general_forest", intensity=2)
    assert steep["fire_load_flp"] > flat["fire_load_flp"]
    assert flat["k_slope"] == 1.0 and steep["k_slope"] == 1.15

    # 燃料类别：Tree Cover(k1.0) vs Grassland(k0.8) → FLP 变化
    tree = build_fire_grid(fire_area_m2=1800, wind_speed=3, slope_deg=10,
                           fuel_type="general_forest", intensity=2)
    grass = build_fire_grid(fire_area_m2=1800, wind_speed=3, slope_deg=10,
                             fuel_type="sparse_grass", intensity=2)
    assert tree["fire_load_flp"] > grass["fire_load_flp"]

    # 适配层：Tree Cover/Grassland 显式映射；未知类别回退场景值且如实标注来源
    tree_env = environment_to_rule_inputs({"terrain": {"slope_deg": 22.5}, "landcover": {"dominant_class": "Tree Cover"}})
    assert tree_env["fuel_type"] == "general_forest" and tree_env["fuel_source"] == "worldcover-fuel-v1"
    assert tree_env["slope_source"] == "environment"
    grass_env = environment_to_rule_inputs({"terrain": {"slope_deg": 5}, "landcover": {"dominant_class": "Grassland"}})
    assert grass_env["fuel_type"] == "sparse_grass"
    unknown = environment_to_rule_inputs({"terrain": {}, "landcover": {"dominant_class": "Built-up"}},
                                         fallback_slope_deg=9, fallback_fuel_type="dense_fuel")
    assert unknown["fuel_type"] == "dense_fuel" and unknown["fuel_source"] == "scenario"
    assert unknown["slope_deg"] == 9 and unknown["slope_source"] == "scenario"


def test_T20_road_subgraph_rebuildable_and_evacuation_labeled_simulated():
    """T20（OPT-P2-03）：道路上下文返回可复建子图（way_id+geometry，非只数量）；
    疏散输出显式携带模拟路径身份（path_mode/path_source）。"""
    from unittest import mock

    from backend.app.services import environment_service as env_svc

    fixture = [{"type": "way", "id": 501,
                "tags": {"highway": "secondary", "name": " test road"},
                "geometry": [{"lon": 118.84, "lat": 32.07}, {"lon": 118.85, "lat": 32.08}]}]
    with mock.patch.object(env_svc, "overpass_query", return_value=fixture):
        context = env_svc.get_road_context(32.07, 118.84, search_radius_m=800)
    assert context["found"] and context["road_count"] == 1
    road = context["nearest_transport"]
    assert road["way_id"] == "way501" and road["provider"] == "osm"
    assert len(road["geometry"]) == 2 and road["geometry"][0] == [118.84, 32.07]
    assert context["graph"]["provider"] == "osm" and context["graph"]["way_ids"] == ["way501"]

    # 疏散模拟身份（BFS 路线输出必须自带标注，前端/报告不可宣称真实最优）
    import math

    from backend.app.skills.registry import EvacuationSkill

    skill = EvacuationSkill()
    result = skill.run({"candidate_generation": {"fire_origin": {"x": 0, "y": 0}},
                        "fire_perception": {"observation": {"fire_area_m2": 1800}},
                        "people_status": "confirmed"})
    assert result.get("path_mode") == "simulated"
    assert result.get("path_source") == "rules-grid-bfs"
    assert result.get("generated_at")


def test_T16_terrain_cell_meters_accounted_from_degrees():
    """T16（OPT-P2-05）：HGT 地理坐标下 cell_m 按纬度换算为米（两轴分列），
    经度轴 < 纬度轴（比率≈cos 纬度），非零有效网格不得返回 0 米。"""
    from backend.app.services.terrain_service import generate_grid

    grid = generate_grid(latitude=32.0725, longitude=118.8415, radius_deg=0.04, size=141)
    assert grid.get("status") == "ok", grid.get("error")
    assert grid["coordinate_system"] == "EPSG:4326"
    x_m, y_m = grid["cell_size_x_m"], grid["cell_size_y_m"]
    assert x_m > 0 and y_m > 0, "非零有效网格不得返回 0 米"
    assert y_m > x_m, "北半球纬 32° 经度轴米距应小于纬度轴"
    ratio = x_m / y_m
    assert 0.80 < ratio < 0.90, f"两轴比率应≈cos(32°)=0.848，实际 {ratio:.3f}"
    assert grid["cell_m"] == pytest.approx((x_m + y_m) / 2, abs=0.2)


def test_T15_environment_snapshot_immutable_and_bound():
    """T15（OPT-P2-04）：环境快照内容哈希寻址——同内容同 ID 不可覆盖；
    数据变化生成新 ID；方案绑定 snapshot_id 可追溯输入证据。"""
    from backend.app.services.analysis_service import _bind_environment_snapshot, _environment_snapshot

    result = {"environment": {"wind_speed": 3.0, "source": "demo"},
              "scene": {"fire_origin_gps": {"latitude": 32.07, "longitude": 118.84}},
              "dispatch_plan": {}}
    snap_v1 = _environment_snapshot(result)
    snapshots = {}
    plan_v1 = {}
    result["environment_snapshots"] = snapshots
    bound_id = _bind_environment_snapshot(result, plan_v1)
    assert bound_id == snap_v1["snapshot_id"]
    assert plan_v1["environment_snapshot_id"] == snap_v1["snapshot_id"]
    v1_content = snapshots[bound_id]["data"]

    # 环境刷新（风速变化）→ 新观测新 ID，V1 快照内容不变
    result["environment"]["wind_speed"] = 8.5
    plan_v2 = {}
    bound_v2 = _bind_environment_snapshot(result, plan_v2)
    assert bound_v2 != bound_id, "环境数据变化应生成新快照 ID"
    assert snapshots[bound_id]["data"] == v1_content, "旧快照内容必须保持不变"
    assert plan_v2["environment_snapshot_id"] == bound_v2

    # 同内容重复绑定复用既有 ID（不产生副本、不覆盖）
    before = snapshots[bound_v2]["captured_at"]
    _bind_environment_snapshot(result, plan_v2)
    assert snapshots[bound_v2]["captured_at"] == before, "同内容快照不可被覆盖"
