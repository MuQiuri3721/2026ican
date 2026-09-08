# 数据字典

领域对象响应带 `schema_version`（`uav-v1`、`fleet-v1`、`inventory-v1`、`analysis-v1`、`uav-dispatch-v1`）、单位、来源和更新时间；工具型/辅助接口（health、environment、terrain、tools、skills、events、rounds）不强制携带。旧字段仅在兼容入口/响应保留，业务规则读取新字段。字段级契约以 [api-contract.md](api-contract.md) 为唯一权威。

坐标口径：任务内所有 `x/y`（`fleet.position`、`scene.fire_origin`、水源 `position`）共用同一套演示相对坐标（米），调度与闭环仿真只在此坐标系内算距离（fleet.position 即无人机基地停机位，FE-17 起统一位于紫霞湖停机坪，火点西南约 830m）；GPS 参考值单独存放（`scene.fire_origin_gps`、`scene.water_sources[].latitude/longitude` 与视觉 `fire_center` 的 `latitude/longitude`），只用于展示与环境查询，不参与距离计算（详见 api-contract.md §1.3）。

| 数据对象 | 关键字段 | 单位/枚举 | 来源与说明 |
|---|---|---|---|
| 场景/环境 | `scene_id`、`terrain_type`、`elevation_m`、`slope_deg`、`wind_speed_mps`、`wind_direction_deg`、`water_sources`、`roads_and_exits` | m、m/s、deg | 紫金山固定场景 JSON/GeoJSON/环境服务；含 `source`、`mode`、时间戳 |
| 火情观测 | `fire_area_m2`、`smoke_area_m2`、`growth_rate`、`confidence`、`fire_center`、`image_width`、`image_height`、`detections`、`fire_type`、`people_status` | m²、m²、比率/h；`confirmed/absent/unknown` | YOLO/PWM-YOLO fixture 或适配器 + `data/vision_observations.json` 口径；视觉不生成风速、真实面积或 SOC |
| 火情负荷 | `fire_load_flp`、`growth_flp_per_hour`、`growth_rate_per_hour`、`fire_grid.intensity`、`fire_grid.cell_count`、`area_per_flp` | FLP、FLP/h、100 m² 网格 | 确定性规则 Tool；FLP 是演示内部量；`area_per_flp` 为本研判自己的 FLP↔面积比率（随场景 FLP 系数变化），monitor/重规划的面积折算统一用它，禁止硬编码 180 |
| UAV | `uav_id`、`subgroup`、`status`、`position`、`soc`、`payload_capacity_kg`、`payload_module`、`agent_remaining`、`agent_unit`、`speed_mps`、`energy_rate_percent_per_hour`、`signal`、`health`、`assigned_task` | SOC/信号/健康度 %；`reconnaissance/suppression/support` | `data/fleet.json`；2+6+4 十二架独立记录，R1–R2、E1–E6、S1–S4（S3/S4 `multi_role: true` 可参战灭火） |
| 药剂模块 | `water_20l`、`co2_6kg`、`sup_10` | W20=L、C6/SUP10=kg | 植被火默认 W20；C6 只用于局部设备/电气热点 |
| 库存 | `water_liters`、`water_modules_w20`、`co2_modules_c6`、`support_boxes_sup10`、`battery_packs`、`water_sources` | L、kg、件 | `data/inventory.json`；库存不得为负 |
| 调度方案 | `plan_id`、`task_id`、`plan_version`、`selected_uavs`、`tasks`、`material_module`、`fire_load_flp`、`growth_rate_per_hour`、`growth_baseline_flp`、`replan_trigger_baseline_flp`、`battery_plan`、`people_branch`、`estimated_control_time`、`feasibility`、`resource_gap`、`alternative_plan`、`replan_trigger`、`scoring` | 时间为 min 区间；W20=L、C6=kg | 确定性调度链（`deterministic_v1_dispatch`）；任务分配在 `tasks`，无 `agent_allocation`/`risk_level` 字段；BE-13 起方案携带 `growth_rate_per_hour`（比例增长率，只随新观测重规划更新）、`growth_baseline_flp`（生成时点负荷）与 `replan_trigger_baseline_flp`（approve/adjust 盖章的触发基线）——增长参数与审批基线分离，审批不得改变火势自然增长；完整字段见 api-contract.md §7 |
| 任务状态 | `status`、`approval`、`resource_locks` | `queued/running/awaiting_confirmation/approved/executing/replanning/completed/terminated/failed` | AnalysisStore；审批确认前不得执行 |
| 反馈轮次 | `round`、`before`、`after`、`changes`、`replan_required`、`replan_triggers`、`next_action` | 1 分钟内部、5 分钟对外 | 监测与重规划接口 |
| 事件 | `timestamp`、`stage`、`message`、`source` | ISO 时间 | 状态、审批、执行、反馈和归档审计 |
| 报告归档 | 输入、方案版本、审批、轮次、事件、资源消耗、结论 | JSON | `data/reports/{task_id}/dispatch_plan.json`（运行时生成，git 忽略）；可追溯任务全生命周期 |

## 兼容字段

旧数据可在入口归一化：`id → uav_id`、`role → subgroup`、`battery → soc`、`payload → agent_remaining`。旧 `/api/monitor/{analysis_id}` 的 `extinguishing_liters` 仅转换为 W20 输入，不反向污染新领域模型。
