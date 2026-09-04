# API 契约（Forest Fire Rescue Agent v0.3.0）

> 本文件是接口、字段、单位、错误码与模型接入协议的**唯一权威**。修改流程见 [CONTRIBUTING.md](../CONTRIBUTING.md) 第 6 节（文档 → 契约测试 → 实现，同一提交）。
> 与代码的对应关系：`backend/app/main.py`（应用装配）、`backend/app/routes/task_routes.py`（任务/平台路由，开发者 A）、`backend/app/routes/environment_routes.py`（环境/等高线路由，开发者 B）、`backend/app/domain/schemas.py`（Pydantic 契约）、`backend/app/domain/store.py`（状态与锁）、`backend/app/pipeline.py`（调度与闭环仿真）、`backend/app/tools/core.py`（模型适配协议）。
> 最近更新：2026-09-04。

## 1. 通用约定

- Base URL：`http://localhost:8000`，Swagger：`http://localhost:8000/docs`。
- CORS 允许源：`http(s)://localhost:5173–5175` 与 `127.0.0.1` 同端口（前端 Vite 默认 5173）。
- 时间戳：ISO 8601 秒级字符串（`2026-09-03T10:00:00` 或带 `Z`）。
- 任务标识：`task_id` 即 `analysis_id`，格式 `analysis-<12 位 hex>`；`plan_id` 格式 `plan-<10 位 hex>`。
- 所有业务数值由确定性规则 Tool 计算；响应中的数字均可在 `configs/simulation.json` 参数下复算。

### 1.1 schema_version 注册表

领域对象必须携带版本；工具型/辅助接口不强制。

| schema_version | 载体 | 出现位置 |
|---|---|---|
| `uav-v1` | 单架 UAV 记录（`UAVRecord`） | fleet 数组元素 |
| `fleet-v1` | 机群响应 | `GET /api/fleet` |
| `inventory-v1` | 库存快照（`InventorySnapshot`） | `GET /api/inventory` |
| `analysis-v1` | 分析任务信封（`AnalysisEnvelope`） | `/api/analyze*` 与 `/api/monitor` 响应 |
| `uav-dispatch-v1` | 调度方案 / 报告文件 | `/api/tasks/{id}/plan`、报告 JSON |

**不带** schema_version 的响应：`/api/health`、`/api/project-status`、`/api/environment`、`/api/terrain/contours`、`/api/tools`、`/api/skills`、`/api/skills/{name}/run`、`/api/analyzes` 外层、`/api/analyze/{id}/events` 外层、`/api/tasks/{id}/rounds` 返回体、`/api/tasks/{id}/events/stream`（SSE）。

### 1.2 单位总表

| 量 | 单位 | 字段后缀约定 |
|---|---|---|
| SOC / 信号 / 健康度 | % | — |
| 载荷容量 / C6、SUP10 药剂 | kg | `_kg` |
| W20 水剂量 | L | `_liters`、`agent_unit="L"` |
| 速度 | m/s | `_mps` |
| 耗电 / 充电速率 | %/h | `_percent_per_hour` / `_soc_per_hour` |
| 风速 | m/s | `_mps` |
| 距离 | m | `_m` |
| 面积 | m²（展示）/ FLP（内部负荷） | `_m2` / `_flp` |
| 火情网格 | 100 m²/格 | `grid_cell_m2` |
| 控制时间 / 轮次时长 | min | `_minutes` |
| 时间戳 | ISO 8601 | `*_at`、`last_updated` |

### 1.3 坐标口径

任务内所有 `x/y` 距离计算共用**同一套演示相对坐标（米）**，包括：

| 数据 | 键名 | 含义 |
|---|---|---|
| `data/fleet.json` 的 `position` | `x/y/z` | 演示相对坐标（米），如 `{"x":120,"y":80,"z":0}` |
| `data/scene.json` 的 `fire_origin` | `x/y` | 同一相对坐标系的火点位置（米） |
| `data/scene.json` 的 `water_sources[].position` | `x/y` | 同一相对坐标系的水源位置（米） |
| 调度与闭环仿真的距离计算 | — | 全部基于上述相对坐标（`simulate_dispatch_candidate`、`simulate_monitor`） |

GPS 参考值单独存放、只用于展示与环境查询，**不参与距离计算**：

| 数据 | 键名 | 含义 |
|---|---|---|
| `data/scene.json` 的 `fire_origin_gps` | `latitude/longitude` | 火点的 GPS 参考位置 |
| `data/scene.json` 的 `water_sources[].latitude/longitude` | `latitude/longitude` | 演示水源的 GPS 参考位置（仅用于地图精准标注，不参与距离计算） |
| 视觉 `fire_center` | `latitude/longitude` | 检测火点的 GPS 参考（历史版本曾用 `x/y` 键存经纬度，已废弃） |
| 环境查询与上传接口 | `latitude/longitude` | 标准经纬度参数，用于真实环境服务 |

### 1.4 错误码表

**HTTP 层**（FastAPI 统一返回 `{"detail": <中文说明>}`）：

| 状态码 | 触发条件 |
|---|---|
| 404 | 任务/方案/Skill 不存在 |
| 409 | 状态冲突：未审批即监测/反馈、过期 `plan_id`、轮次号倒退、终态任务操作、资源已被其他任务锁定 |
| 413 | 上传超过 200 MB |
| 415 | 上传类型不在 `image/jpeg, image/png, video/mp4`，或文件魔数校验失败 |
| 422 | 参数校验失败（Pydantic、未知 `scene_id`、经纬度/半径越界、负值输入） |
| 502 | Skill 链执行失败（`SkillExecutionError`）或运行时错误 |

**Tool 层**（信封内 `error.code`）：

| code | 含义 |
|---|---|
| `scene_not_found` | 未知 `scene_id` |
| `invalid_input` | 通用参数非法（负数、越界等） |
| `invalid_coordinates` | 经纬度非法或超出范围 |
| `invalid_mode` | `environment_mode` 不是 demo/real/auto/offline |
| `coordinates_required` | `real` 模式缺少经纬度 |
| `invalid_inventory` | 库存出现负数 |
| `invalid_transition` | 非法 UAV 状态转换 |
| `tool_execution_failed` | Tool 未捕获异常 |
| `environment_unavailable` | 真实环境服务不可用 |
| `detector_unavailable` | YOLO 端点不可用（strict_real） |
| `vlm_unavailable` | VLM 端点不可用（strict_real） |
| `yolo_endpoint_unavailable` / `vlm_endpoint_unavailable` | 非 strict_real 下回退时的 `adapter_fallback.code` |
| `analysis_failed` | 任务级失败（信封 `error.error_code`） |
| `video_path_required` / `opencv_not_available` / `video_unavailable` | `extract_frames` 不可用状态（`status="not_available"`） |

### 1.5 任务状态机

枚举（`domain/schemas.py::TaskStatus`）：

```text
queued → running → awaiting_confirmation → executing → completed
                                   │           ↑
                                   │        replanning（生成新版本后回到 awaiting_confirmation）
                                   ├─ reject → 停留在 awaiting_confirmation（释放资源锁）
                                   └─ 任意非终态 → terminated；任意状态 → failed
```

- **`approved` 状态当前保留在枚举中但代码不会进入**：审批 `approve` 成功后直接置 `executing` 并锁定资源（`store.approval`）。
- 终态 `completed / terminated / failed` 禁止审批、重规划、反馈与监测（返回 409）。
- 每次审批、重规划、监测、反馈都写入 `events`（新事件插在前）。

## 2. 系统与元信息接口

### 2.1 `GET /api/health`

```json
{"status": "ok", "service": "forest-fire-agent", "version": "0.3.0"}
```

### 2.2 `GET /api/project-status`

返回框架/演示管线/智能体层状态、`yolo`/`vlm` 接入状态（当前 `"pending"`）、环境模式列表与 Tool/Skill 数量、`last_checked`。

### 2.3 `GET /api/tools` · `GET /api/skills`

```json
{"tools": ["analyze_with_vlm", "assess_fire_level", "...共 46 个确定性 Tool"]}
{"skills": ["candidate_generation", "closed_loop_monitoring", "...共 15 个 Skill"]}
```

### 2.4 `POST /api/skills/{skill_name}/run`（兼容调试接口）

请求体为 `AnalysisInput`（见 §6.1），单步运行指定 Skill 并返回其结构化结果；用于调试，**不产生任务、不写状态**，结果不得与主任务结果混用。未知 Skill 404；Skill 内部失败（`ok:false`）映射为 502。

## 3. 环境与地形接口

### 3.1 `GET /api/environment`

Query：`scene_id`（默认 `forest-demo-01`）、`latitude`、`longitude`、`environment_mode`（`demo|real|auto|offline`，缺省 auto：有坐标走 real、无坐标走 demo）、`water_radius_m`、`road_radius_m`（默认 5000，1–50000）。

响应（EnvironmentTool 统一信封，真实/演示同构）：

```json
{
  "scene_id": "forest-demo-01", "name": "紫金山演示林区",
  "mode": "demo", "status": "ok", "source": "demo-data", "collected_at": "2026-09-05T18:00:00",
  "wind_speed": 6.5, "wind_direction": "西北",
  "altitude": 320, "terrain": "丘陵",
  "water_sources": [{"name": "北侧蓄水池", "distance_m": 150, "available": true, "position": {"x": 20, "y": -20}, "latitude": 32.0701, "longitude": 118.8432}],
  "nearest_water": {"...同上首项"}, "preferred_water": {"..."},
  "road_context": null, "landcover": null, "raw": {"...完整数据"}
}
```

- `mode` 取值：`demo`（固定场景）/ `real`（环境服务）/ `demo-fallback`（失败回退，附 `fallback: {code, message}`）/ 真实缓存过期时 `status="stale"` 且 `stale=true`。
- `collected_at` 为数据装配/抓取时刻（ISO 秒级）；缓存命中时随缓存返回，即数据实际采集时间。
- `real` 模式必须同时提供 `latitude` 与 `longitude`，否则 422 或 fallback（取决于模式）。
- `offline` 请求模式返回 `mode=demo` 且 `metadata: {"offline": true, "network": "disabled"}`。

### 3.2 `GET /api/terrain/contours`

Query：`latitude`（默认 32.0725，紫金山主峰）、`longitude`（默认 118.8415）、`radius_deg`（默认 0.04，≤0.2）、`interval_m`（默认 20，1–500）、`max_points`（默认 180，20–240）。

成功：GeoJSON `{"type": "FeatureCollection", "status": "ok", "source": "N32E118.hgt", "location": {...}, "bounds": {"radius_deg": 0.04}, "interval_m": 20, "features": [...]}`。
失败不抛 5xx：返回空 FeatureCollection，`status="fallback"`、`source="demo-data-fallback"`，`fallback.code ∈ {invalid_parameters, invalid_coordinates, rasterio_unavailable, dem_no_data, dem_unavailable}`。

## 4. 资源接口

### 4.1 `GET /api/fleet?task_id=<可选>`

- 不带 `task_id`：返回 `data/fleet.json` 归一化后的 2+4+2 全局快照。
- 带 `task_id`：返回该任务执行期间的任务内快照（含监测演化后的 SOC/状态/药剂），任务不存在 404。

```json
{
  "schema_version": "fleet-v1",
  "count": 8,
  "task_id": null,
  "fleet": [
    {"schema_version": "uav-v1", "uav_id": "E1", "id": "E1",
     "subgroup": "suppression", "role": "firefighting",
     "status": "available",
     "position": {"x": 160, "y": 100, "z": 0},
     "soc": 92, "battery": 92,
     "payload_capacity_kg": 25, "payload_module": "water_20l",
     "agent_remaining": 20, "payload": 20, "agent_unit": "L",
     "speed_mps": 8, "energy_rate_percent_per_hour": 270,
     "signal": 90, "health": 100, "assigned_task": null,
     "last_updated": "2026-09-03T10:00:00Z"}
  ]
}
```

`subgroup` 枚举：`reconnaissance | suppression | support`；`role` 是兼容别名（`firefighting` ↔ suppression）。`status` 枚举：`available | assigned | flying | working | returning | servicing | charging | fault`。`payload_module` 枚举：`none | water_20l | co2_6kg | sup_10`；`agent_unit` 必须与模块匹配（W20→L，C6/SUP10→kg）。

### 4.2 `GET /api/inventory?task_id=<可选>`

```json
{"schema_version": "inventory-v1", "water_liters": 240, "water_modules_w20": 12, "co2_modules_c6": 4,
 "support_boxes_sup10": 6, "battery_packs": 16,
 "forward_supply_points": [{"id": "base", "name": "北侧前置补给点", "position": {"x": 100, "y": 60}, "available": true}],
 "water_sources": [{"id": "reservoir-north", "name": "北侧蓄水池", "available": true, "capacity_liters": 1200, "distance_m": 680, "safe": true}],
 "dry_powder_kg": 60, "nearby_water_available": true, "last_updated": "...", "task_id": "仅带 task_id 时出现"}
```

库存数值恒不为负；带 `task_id` 时返回任务内快照。

## 5. 任务生命周期接口

任务由 `/api/analyze`（JSON 输入）或 `/api/analyze/upload`（文件上传）创建；`task_id == analysis_id`。**不存在 `POST /api/tasks`。** 任务、方案版本、轮次、事件与资源锁经 SQLite 写穿持久化（`data/analysis_store.db`，git 忽略），服务重启后自动恢复。

### 5.1 `POST /api/analyze`

请求体 `AnalysisInput`（全部字段可选，除非注明）：

| 字段 | 类型/默认 | 说明 |
|---|---|---|
| `scene_id` | string，默认 `forest-demo-01` | 未知场景 422 |
| `image_name` / `image_path` / `file_id` | string/null | 影像标识；`small` 命中 fixture 小火观测 |
| `use_vlm` | bool，默认 false | 是否调用 VLM 解释 |
| `fleet_snapshot` | string，默认 `"default"` | 兼容保留 |
| `latitude` / `longitude` | float/null | 范围 ±90 / ±180 |
| `environment_mode` | string/null | `demo|real|auto|offline` |
| `water_search_radius_m` / `road_search_radius_m` | int，默认 5000（别名 `water_radius_m`/`road_radius_m`） | 1–50000 |
| `metadata` | object/null | 透传到环境结果 |
| `fire_type` | string，默认 `"vegetation"` | `electrical/oil/chemical` 触发 C6 |
| `people_status` | `confirmed|absent|unknown`，默认 unknown | 人员分支 |
| `constraints` | object/null | 支持 `max_drones`（1–4）、`disabled_uavs`、`material_module`、`target_minutes`（分钟硬时限：全部可控候选超时时判不可控并输出 `time_limit` 缺口） |

成功响应：完整任务信封 `AnalysisEnvelope`，`status="awaiting_confirmation"`：

```json
{
  "analysis_id": "analysis-0097b06a834b",
  "status": "awaiting_confirmation",
  "created_at": "...", "updated_at": "...",
  "schema_version": "analysis-v1",
  "input": {"...请求体"},
  "result": {
    "fire_assessment": {"level": 3, "label": "III 级 · 高风险", "fire_area_m2": 1800, "smoke_area_m2": 4200,
      "confidence": 0.91, "risk_score": 0.552, "growth_rate": 0.42, "fire_load_flp": 245.7,
      "growth_flp_per_hour": 103.19, "fire_grid": {"cell_area_m2": 100, "cell_count": 18, "intensity": 3,
      "k_fuel": 1.0, "k_wind": 1.2, "k_slope": 1.0, "fuel_type": "general_forest"},
      "wind_band": {"band": 1, "label": "4–6 m/s", "k_wind": 1.2, "wind_speed": 6.5},
      "slope_deg": 12, "spread_direction": "西北", "fire_type": "vegetation"},
    "environment": {"wind_speed": 6.5, "wind_direction": "西北", "altitude": 320, "terrain": "丘陵",
      "nearest_water_distance_m": 800},
    "dispatch_plan": {"...见 §7"},
    "source_image": "small-fire.jpg",
    "data_mode": "固定演示数据 · 规则引擎",
    "pipeline_stages": [{"id": "ingest", "label": "影像接入", "status": "completed", "source": "上传文件"}, "..."],
    "fleet": ["...同 §4.1 归一化 8 架"],
    "inventory": {"...同 §4.2"},
    "explanation": "当前为III 级 · 高风险，火情负荷 245.7 FLP（18 个 100m² 网格）...",
    "agent": {"skill_chain": {"...9 步核心 Skill 链结构化结果（确认有人时追加 evacuation；route_planning/task_execution/closed_loop_monitoring 已移出核心链，仅存于兼容注册表）"}, "chain_order": ["..."], "data_mode": "demo-stub + rules"},
    "vlm_explanation": {"summary": "...", "conflicts": [], "anomalies": [], "source": "rule-explainer-fallback", "mode": "fallback"},
    "environment_source": {"mode": "...", "source": "...", "status": "...", "stale": false, "location": {...}}
  },
  "stages": ["...同 result.pipeline_stages"],
  "events": [{"timestamp": "...", "stage": "dispatch", "message": "分析链完成并生成调度方案", "source": "rules"}],
  "error": null, "monitor_round": 0,
  "plan_versions": [{"...首个方案，含 plan_id/plan_version=1"}],
  "approval": null, "rounds": [], "resource_locks": []
}
```

失败：`SkillExecutionError`/`RuntimeError` → 502；`KeyError/ValueError/TypeError` → 422；任务信封置 `status="failed"` 且 `error={"error_code": "analysis_failed", "message": ..., "stage": "agent_chain"}`。

### 5.2 `POST /api/analyze/upload`（multipart/form-data）

Form 字段（全部为 multipart 表单字段，显式 `Form(...)` 绑定）：`file`（必填，≤200MB，JPG/PNG/MP4，服务端做魔数校验）、`frames`（可选，1+ 张早前帧图片；主文件自动作为序列最新一帧，共 ≥2 帧时逐帧检测并输出面积趋势）、`scene_id`、`use_vlm`、`latitude`、`longitude`、`environment_mode`、`people_status`（confirmed/absent/unknown，confirmed 时核心链追加疏散分支）、`fire_type`（默认 `vegetation`；`electrical/oil/chemical` 触发 C6，语义同 §5.1）、`constraints`（可选，JSON object 字符串，如 `{"max_drones": 2}`，语义同 §5.1；非法 JSON 422）、`water_search_radius_m`、`road_search_radius_m`。文件落盘 `uploads/<12hex>-<原名>`，随后行为与 `POST /api/analyze` 一致。类型不符 415、超限 413、魔数不符 415（上传文件随之删除）。

多帧序列响应附加字段：`result.visual_sequence = {"frame_count": N, "frames": [{image_name, fire_area_m2, smoke_area_m2, growth_rate, confidence}], "trend": {status, trend, growth_rate, areas_m2}}`；趋势状态 `ok` 时序列增长率与最新帧面积显式驱动火情重算。

> MP4 会被接收但不等于视频分析：抽帧 Tool `extract_frames` 依赖 OpenCV 且当前未挂入主链。

### 5.3 `GET /api/analyzes` · `GET /api/analyze/{analysis_id}` · `GET /api/analyze/{analysis_id}/events`

- 列表：`{"items": [AnalysisEnvelope...]}`（新任务在前）。
- 单个：`AnalysisEnvelope`；不存在 404。
- 事件：`{"analysis_id": "...", "events": [TaskEvent...]}`，`TaskEvent = {timestamp, stage, message, source}`。

### 5.4 `GET /api/tasks/{task_id}/plan`

```json
{"schema_version": "uav-dispatch-v1", "task_id": "analysis-...", "plan": {"...最新方案，见 §7"}, "versions": ["...全部历史方案"]}
```

无方案 404。

### 5.5 `POST /api/tasks/{task_id}/approval`

请求体 `ApprovalRequest`：

| 字段 | 说明 |
|---|---|
| `action` | 必填：`approve / reject / adjust / terminate`，其他值 422 |
| `plan_id` | 可选；提供时必须等于当前最新方案，否则 409 |
| `constraints` | 可选；`adjust` 时作为新方案约束 |
| `reason` | 可选，记录进 `approval` |
| `idempotency_key` | 可选；与最近一次审批的 action+key 相同时直接幂等返回当前任务 |

状态前提（不满足 409）：

| action | 允许的当前状态 | 结果状态 | 资源锁 |
|---|---|---|---|
| `approve` | `awaiting_confirmation` / `replanning`（枚举含 `approved`，当前不会出现） | `executing` | 锁定方案的 E 组（无方案时回退灭火组前 4 架） |
| `reject` | `awaiting_confirmation` / `replanning` | `awaiting_confirmation` | 释放 |
| `adjust` | `awaiting_confirmation` / `approved` / `executing` / `replanning` | `replanning` → 自动重规划后 `awaiting_confirmation` | 释放旧锁 |
| `terminate` | 任意非终态 | `terminated` | 释放 |

响应：`approve/reject/terminate` 返回完整 `AnalysisEnvelope`（含 `approval`、`resource_locks`、事件）；**`adjust` 返回 plan 信封**（同 §5.4，`plan` 为新版本、`plan_version` 递增）。无灭火机可锁 409。

### 5.6 `POST /api/tasks/{task_id}/replan`

请求体 `ReplanRequest`：`triggers: string[]`（重规划原因）、`constraints`（可选，覆盖约束）、`observation`（可选，键 `fire_area_m2 / smoke_area_m2 / growth_rate / fire_load_flp` 注入火情）、`people_status`（可选）。

行为：释放旧资源锁 → `status=replanning` → 基于任务内当前 fleet/inventory 快照重新运行 V1 调度 → 新 `plan_version`（旧版本+1）、`replan_trigger=triggers` → `status=awaiting_confirmation`。响应同 §5.4 plan 信封。终态任务 409。

### 5.7 `POST /api/tasks/{task_id}/rounds`

请求体 `FeedbackRoundInput`（5 分钟反馈轮次）：

| 字段 | 默认 | 说明 |
|---|---|---|
| `round` | 必填 | 必须等于 `monitor_round + 1`，否则 409 |
| `fire_load_flp` / `growth_rate` / `wind_speed` | null | 本轮观测值；风速重规划按档位（0–4/4–6/6–8 m/s）比较 |
| `people_status` | null | 变化触发 `people_status_changed` |
| `fleet_snapshot` / `inventory` | null | 兼容保留；**任务快照始终以 Store 为准** |
| `elapsed_minutes` | 5（>0，≤120） | 内部按 1 分钟步长推进 |
| `extinguishing_liters` | 0 | 本轮喷洒上限（L） |

响应 `round_data`：

```json
{
  "round": 1,
  "before": {"fire_load_flp": 245.7, "growth_rate": 0.42, "wind_speed": 6.5, "people_status": "unknown",
             "fleet": ["...任务内快照"], "inventory": {"...任务内快照"}},
  "after": {"...simulate_monitor 结果 + 最新 fleet/inventory"},
  "changes": {"fire_load_flp": [after, before] 或 null, "action": "continue"},
  "replan_required": false,
  "replan_triggers": ["fire_load_increase_over_20_percent", "wind_band_changed", "people_status_changed", "resource_or_soc"],
  "next_action": "continue | awaiting_confirmation | resupply | reinforce | return | finish"
}
```

`before` 恒为 Store 上一轮真实快照，不接受客户端传入值。触发关键事件时自动生成新方案版本并持久化，新方案仍需审批。非 `executing` 状态 409。

### 5.8 `GET /api/tasks/{task_id}/report` · `GET /api/tasks/{task_id}/report/download`

- report：`{"task_id", "input", "status", "plan_versions", "rounds", "events", "result"}`，读取时同步刷新落盘。
- download：返回文件 `dispatch_plan.json`（`application/json`）。报告落盘路径：`data/reports/{task_id}/dispatch_plan.json`（原子写：临时文件 + replace；目录已列入 `.gitignore`）。任务不存在 404。

### 5.9 `POST /api/monitor/{analysis_id}`（旧兼容接口）

请求体 `MonitorInput`：`elapsed_minutes`（默认 5）、`extinguishing_liters`（默认 40）、`image_name`、`fleet_snapshot`、`inventory`（后两者兼容保留，不覆盖任务快照）。

行为与 §5.7 的底层监测一致：仅允许 `executing` 状态（否则 409）；旧 `extinguishing_liters` 仅在入口作为 W20 喷洒输入，不把旧面积口径写入领域模型。响应：`{**AnalysisEnvelope, "action": "continue|resupply|reinforce|return|finish"}`，监测细节在 `result.monitor`（含 `next_fire_load_flp`、`replan_triggers`、`resource_consumed`、`availability`、`battery_plan`、`next_fleet`、`next_inventory`）。

### 5.10 `GET /api/tasks/{task_id}/events/stream`（SSE 事件流）

Query：`once`（可选，`1` = 仅推送当前事件快照后结束，供一次性拉取与测试）。

流程：先发送 `retry: 3000`，再按时间序逐条 `data: {TaskEvent JSON}`；随后保持连接（上限约 5 分钟，客户端 EventSource 自动重连续传），每秒检查新事件并增量推送，15 秒无事件发送 `: keep-alive` 注释；任务进入终态且事件推尽后发送 `event: done`（`data: {"status": ...}`）并结束。任务不存在 404。响应头 `Content-Type: text/event-stream`、`Cache-Control: no-cache`。

## 6. 数据契约

### 6.1 核心对象速览

- `TaskEvent`：`{timestamp, stage, message, source}`，`source ∈ {system, rules, user, api, upload}`。
- `AnalysisEnvelope`：见 §5.1 响应示例；`monitor_round` 为已完成的监测/轮次次数，是 `round` 递增的基准。
- `DispatchPlan`（实际输出字段，`deterministic_v1_dispatch`）：见 §7。

### 6.2 数据文件

| 文件 | 角色 | 变更规则 |
|---|---|---|
| `data/scene.json` | 固定演示场景（风、坡度、燃料、火点、水源） | 视同契约（CONTRIBUTING 6.3） |
| `data/fleet.json` | 2+4+2 初始机群 | 同上 |
| `data/inventory.json` | 初始库存 | 同上 |
| `data/vision_observations.json` | 视觉 fixture（default / small-fire） | YOLO 接入的字段对齐基准 |
| `configs/simulation.json` | 规则参数（阈值、权重、κ、风档、评分权重、充换电、喷洒） | 同上 |
| `data/reports/{task_id}/dispatch_plan.json` | 任务归档报告 | 运行时生成，git 忽略 |
| `backend/N32E118.hgt` | 紫金山 DEM | 等高线服务数据源 |

## 7. DispatchPlan 实际字段（uav-dispatch-v1）

```json
{
  "schema_version": "uav-dispatch-v1",
  "plan_id": "plan-1a2b3c4d5e",
  "task_id": "analysis-0097b06a834b",
  "plan_version": 1,
  "generated_at": "2026-09-03T22:31:04",
  "fleet_shape": {"reconnaissance": 2, "suppression": 4, "support": 2},
  "can_control": true,
  "feasibility": true,
  "required_drones": 2,
  "selected_uavs": ["R1", "E1", "E2", "S1"],
  "recommended_material": "water",
  "material_module": "water_20l",
  "material_amount": 80.0,
  "fire_load_flp": 245.7,
  "growth_flp_per_hour": 103.19,
  "effective_flp": 92.4,
  "resource_gap": [{"resource": "water_liters", "required": 100, "available": 60, "gap": 40, "resource_gap": true}],
  "battery_plan": [{"uav_id": "E1", "soc_before": 92, "soc_after_return": 64.3, "sortie_soc_cost": 13.85,
    "sorties": 2, "swaps": 0, "refills": 1, "reserve_percent": 25, "state": "ready", "outbound_minutes": 0.52}],
  "people_branch": "absent",
  "fire_grid": {"cell_area_m2": 100, "cell_count": 18},
  "wind_band": {"band": 1, "label": "4–6 m/s", "k_wind": 1.2, "wind_speed": 6.5},
  "scoring": {"method": "J=0.40T+0.30B+0.15E+0.10M+0.05N", "lower_is_better": true,
    "chosen": {"score": 0.234, "parts": {"time": 0.1, "residual": 0.0, "energy": 0.19, "material": 0.25, "change": 0.25}},
    "simulation": {"controlled": true, "rounds_used": 2, "stalled_reason": null, "swaps": 0, "refills": 1}},
  "water_source_plan": {"mode": "base", "fill_minutes": 4, "reason": "优先基地补给；..."},
  "replan_trigger": ["fire_load_increase_over_20_percent", "wind_band_changed", "soc_below_return_threshold",
    "agent_insufficient", "people_status_changed"],
  "estimated_control_time": {"earliest_minutes": 12, "latest_minutes": 17, "window_minutes": [12, 17],
    "unit": "min", "simulated": true},
  "estimated_minutes": 17,
  "alternative_plan": [{"selected_uavs": ["E1", "E3"], "feasibility": true, "effective_flp": 72.0,
    "score": 0.301, "control_minutes": 15.0}],
  "tasks": [{"drone_id": "R1", "task": "持续侦察", "branch": "reconnaissance"},
    {"drone_id": "E1", "task": "主力灭火", "module": "water_20l", "target_flp": 122.85},
    {"drone_id": "S1", "task": "物流补给", "branch": "support"}],
  "reason": "V1 离散仿真可控，按 J 评分选出最优组合"
}
```

与历史规划示例的差异（以本节为准）：

- 任务分配在 `tasks`（`drone_id/task/module/target_flp/branch`）；**没有** `agent_allocation` 字段；
- **没有** `risk_level` 字段（风险由 `fire_assessment.level` 承载）；
- `battery_plan` 条目为 `{uav_id, soc_before, soc_after_return, sortie_soc_cost, sorties, swaps, refills, reserve_percent, state, outbound_minutes}`，不是 `outbound_soc/task_soc/return_soc/reserve_soc`；
- `estimated_control_time` 为 `{earliest_minutes, latest_minutes, window_minutes, unit, simulated}`，不是 `{min, max}`；
- 不可控时 `estimated_control_time.window_minutes=null`、`can_control=false`，并输出 `resource_gap`（不产出虚假时间窗口）。

## 8. 调度与闭环关键规则（契约级）

- 候选生成：E 子群枚举 1–4 架组合（受 `constraints.max_drones`、`disabled_uavs` 限制），硬约束过滤（status ∈ available/assigned、health≥60、**SOC≥35% 新任务底线**（`new_task_floor_soc_percent`，25% 仅为返航阈值）、模块与火情类型兼容）→ 5 分钟离散仿真 → `J = 0.40T + 0.30B + 0.15E + 0.10M + 0.05N`（越小越优）→ 最优 + 备选（≤8 个）。
- 就地取水六条件评估（`select_water_source`）真实执行：available、safe_access、容量≥20L、路线安全、循环后 SOC≥25%、比基地节省≥5 分钟；不通过则 `water_source_plan.mode=base` 并在 reason 记录评估结论。
- 硬时限：`constraints.target_minutes` 剔除全部超时可控方案；全超时时判不可控并输出 `time_limit` 缺口（`estimated_control_time` 置空，见 §7）。
- 闭环监测输出 `emergency_units`（SOC<`emergency_soc_percent`(15%) 的任务机，规则 V1 §4.2 应急回收标记）。
- 有人分支（people=confirmed）核心链追加疏散：`result.agent.skill_chain.evacuation`（BFS 路线避开火点风险网格，含 steps/estimated_minutes/risk_cells）。
- 至少 1 架 R 在线监测；S 按人员分支分配（confirmed→通信/疏散指引，absent→物流，unknown→复核与后备）。
- 药剂 κ 表（`configs/simulation.json`）：植被火 W20=1.0、C6=0.25；电气水剂=0（排除）、C6=1.5。`fire_type ∈ {electrical, oil, chemical}` 默认 C6；调度仿真/闭环监测的 κ 一律按真实 `fire_type` 查表，油类与化学品火归一化到电气行（C6=1.5、W20=0）。
- 重规划触发：FLP 上升 >20%、风速档位变化、预计返航 SOC<25%、药剂不足、人员状态变化、资源/续航动作（resupply/return/reinforce）。
- 资源锁跨任务互斥：`approved/executing/replanning` 状态任务的锁集合与其他任务候选交集非空时 409。

## 9. YOLO 检测适配协议（FIRE_YOLO_ENDPOINT）

平台侧实现：`backend/app/tools/core.py::detect_fire`。YOLO 开发者只需交付一个独立 HTTP 服务，**不修改平台代码**。

- 启用方式：环境变量 `FIRE_YOLO_ENDPOINT`（如 `http://127.0.0.1:9000/detect`）；未设置时平台使用 fixture（`data/vision_observations.json`），`mode=demo`。
- 请求：`POST <endpoint>`，body 为**原始图片字节**，`Content-Type: application/octet-stream`；仅当任务带 `image_path` 时才会调用。
- 超时：5 秒。
- 响应：JSON object，**必须**包含 `detections` 数组；否则视为协议错误。

```json
{
  "detections": [
    {"class_name": "fire", "confidence": 0.93, "box": [820, 410, 1130, 760]},
    {"class_name": "smoke", "confidence": 0.89, "box": [650, 180, 1420, 820]}
  ],
  "image_width": 1920, "image_height": 1080,
  "fire_area_m2": 1800, "smoke_area_m2": 4200,
  "growth_rate": 0.42, "confidence": 0.91,
  "fire_center": {"x": 118.78, "y": 32.04}
}
```

字段约定：`class_name ∈ {fire, smoke, building, obstacle, ...}`（`fire/smoke` 参与面积统计）；`box = [x1, y1, x2, y2]` 像素坐标；`fire_center.x/y` 为经度/纬度数值（见 §1.3 坐标口径）。`detections` 之后的字段均为可选——缺省时由规则 Tool（`calculate_fire_metrics` 等）从检测框推算。

失败行为：

| 场景 | strict_real（`environment_mode="real"`） | 默认/auto |
|---|---|---|
| 端点未配置 | 不调用，走 fixture | 走 fixture |
| 调用失败/响应非法 | `{"status": "error", "mode": "real", "source": "pwm-yolo-adapter", "error": {"code": "detector_unavailable", "message": ...}, "detections": []}` → Skill 链返回 `ok:false` → 任务 502 | 回退 fixture，附 `adapter_fallback: {"code": "yolo_endpoint_unavailable", "message": ...}` |

接入成功后结果带 `mode="real"`、`source="pwm-yolo-adapter"`。前端与报告以 `mode/source` 展示来源，未配置端点时不得宣称真实识别。

## 10. VLM 解释适配协议（FIRE_VLM_ENDPOINT）

平台侧实现：`backend/app/tools/core.py::analyze_with_vlm`。VLM 只做观察与解释，**不得输出/覆盖 FLP、SOC、药剂需求、无人机数量、时间等规则数字**。

- 启用方式：环境变量 `FIRE_VLM_ENDPOINT`；未设置时使用规则回退解释器 `vlm_explain_fire`（`mode="fallback"`、`source="rule-explainer-fallback"`）。
- 请求：`POST <endpoint>`，JSON：

```json
{"observation": {"...detect_fire 输出"}, "environment": {"...环境结果"}, "people_status": "unknown"}
```

- 超时：5 秒。响应：JSON object（无必需字段），建议结构对齐规则回退解释器：`summary / people / buildings / roads / obstacles / fire_trend / conflicts[] / anomalies[]`；平台自动补 `source="vlm-adapter"`、`mode="real"`。
- 失败行为同 §9：strict_real 返回 `{"status": "error", "error": {"code": "vlm_unavailable"}}`；否则回退规则解释并附 `adapter_fallback: {"code": "vlm_endpoint_unavailable"}`。

## 11. 兼容层

- 旧字段归一化（入口执行，响应同时保留新旧别名）：`id → uav_id`、`role → subgroup`（`firefighting → suppression`）、`battery → soc`、`payload → agent_remaining`。
- `POST /api/monitor/{analysis_id}` 为旧闭环入口，新集成一律使用 `/api/tasks/{task_id}/rounds`。
- `FireAnalysisSkill` 与 `POST /api/skills/{skill_name}/run` 是兼容调试通道，输出不进入任务状态，不得与 `AnalysisEnvelope` 混用。
