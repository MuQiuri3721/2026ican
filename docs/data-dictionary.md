# 数据字典

所有接口响应带 `schema_version`、单位、来源和更新时间；旧字段仅在兼容入口/响应保留，业务规则读取新字段。

| 数据对象 | 关键字段 | 单位/枚举 | 来源与说明 |
|---|---|---|---|
| 场景/环境 | `scene_id`、`terrain_type`、`elevation_m`、`slope_deg`、`wind_speed_mps`、`wind_direction_deg`、`water_sources`、`roads_and_exits` | m、m/s、deg | 紫金山固定场景 JSON/GeoJSON/环境服务；含 `source`、`mode`、时间戳 |
| 火情观测 | `fire_id`、`detected_classes`、`confidence`、`image_area_ratio`、`calibrated_cells`、`fire_type`、`people_status` | 比例、置信度；`confirmed/absent/unknown` | YOLO/PWM-YOLO fixture 或适配器；视觉不生成风速、真实面积或 SOC |
| 火情负荷 | `fire_load_flp`、`growth_flp_per_hour`、`intensity_level`、`target_cells` | FLP、FLP/h、100 m² 网格 | 确定性规则 Tool；FLP 是演示内部量 |
| UAV | `uav_id`、`subgroup`、`status`、`position`、`soc`、`payload_capacity_kg`、`payload_module`、`agent_remaining`、`agent_unit`、`speed_mps`、`energy_rate_percent_per_hour`、`signal`、`health`、`assigned_task` | SOC/信号/健康度 %；`reconnaissance/suppression/support` | `data/fleet.json`；2+4+2 八架独立记录，R1–R2、E1–E4、S1–S2 |
| 药剂模块 | `water_20l`、`co2_6kg`、`sup_10` | W20=L、C6/SUP10=kg | 植被火默认 W20；C6 只用于局部设备/电气热点 |
| 库存 | `water_liters`、`water_modules_w20`、`co2_modules_c6`、`support_boxes_sup10`、`battery_packs`、`water_sources` | L、kg、件 | `data/inventory.json`；库存不得为负 |
| 调度方案 | `plan_id`、`task_id`、`plan_version`、`selected_uavs`、`agent_allocation`、`battery_plan`、`people_branch`、`estimated_control_time`、`feasibility`、`resource_gap`、`alternative_plan`、`replan_trigger` | 时间为 min 区间 | 确定性调度链；保留来源和硬约束检查 |
| 任务状态 | `status`、`approval`、`resource_locks` | `queued/running/awaiting_confirmation/approved/executing/replanning/completed/terminated/failed` | AnalysisStore；审批确认前不得执行 |
| 反馈轮次 | `round`、`before`、`after`、`changes`、`replan_required`、`replan_triggers`、`next_action` | 1 分钟内部、5 分钟对外 | 监测与重规划接口 |
| 事件 | `timestamp`、`stage`、`message`、`source` | ISO 时间 | 状态、审批、执行、反馈和归档审计 |
| 报告归档 | 输入、方案版本、审批、轮次、事件、资源消耗、结论 | JSON | `reports/` 或报告服务输出；可追溯任务全生命周期 |

## 兼容字段

旧数据可在入口归一化：`id → uav_id`、`role → subgroup`、`battery → soc`、`payload → agent_remaining`。旧 `/api/monitor/{analysis_id}` 的 `extinguishing_liters` 仅转换为 W20 输入，不反向污染新领域模型。
