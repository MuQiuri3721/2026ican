# 系统架构与算法总览

> 本文由原 `architecture.md`、`agent-architecture.md`、`algorithm.md` 三份同类文档合并而成（BE-14 文档整理，2026-09-08），并同步当前实现口径：核心 Skill 链 9 步、SQLite 写穿 Store、SSE 事件流、2+6+4 十二架机群、统一分钟推进核心（BE-13）。

## 一、运行时链路

```text
Vue 指挥工作台
   ↓ JSON / multipart
FastAPI API
   ↓
AnalysisService（任务生命周期与统一用例）
   ├─ AnalysisStore：任务、方案版本、审批、轮次、事件、资源锁（SQLite 写穿持久化）
   ├─ Environment/Terrain Service：紫金山环境、道路、水源、等高线（Open-Meteo + OSM，离线回退）
   └─ SkillOrchestrator
        ↓ 核心链 9 步（skills/orchestrator.py CORE_ORDER）
火情感知 → 环境研判 → 火情评估 → 人员分支
→ 候选生成 → 硬约束过滤 → 调度评分 → 审批准备 → 报告归档
        ↓
ToolRegistry → 确定性规则 Tool / JSON 数据 / 适配器
```

注：route_planning / task_execution / closed_loop_monitoring 已移出核心链（保留在注册表供兼容通道单独调用）；闭环监测由 rounds API 驱动 `rules/simulation.py` 的统一分钟推进核心承担，报告归档在 service 层 `_persist_dispatch_report` 完成。

## 二、代码边界（分层职责）

- `domain/`：Pydantic 契约、领域枚举、任务状态和事件。
- `routes/`：只负责协议、输入校验和 HTTP 错误映射。
- `services/analysis_service.py`：统一任务用例——任务状态、方案版本、审批、资源锁、反馈轮次和报告。
- `agents/`：生成并执行有依赖的固定计划，不让模型绕过约束（blackboard 黑板协议协作 + GLM advisory）。
- `skills/`：组合 Tool，传递结构化上下文，处理有人/无人/unknown 分支。
- `tools/`：单一、可复算的动作，统一返回 `ok/tool/source/data/error`；FLP、SOC、药剂需求、可行性和评分必须由确定性 Tool 产出。
- `rules/`：冻结规则与唯一分钟推进核心 `advance_one_minute`（BE-13）——预测（状态副本）与执行（任务真实状态）调用同一套物理规则。
- Adapter 是 YOLO/VLM、GIS、气象、数据库和飞控的替换点（见 §六）。

模型不能直接覆盖火情等级、无人机数量、耗电、灭火效果、资源缺口或完成时间。`offline/demo-fallback` 仅是明确标注来源的演示降级路径。

## 三、状态与审批

```text
queued → running → awaiting_confirmation → approved → executing
                                      ↘ reject/adjust（adjust 生成新版本走再审批）
executing → replanning → awaiting_confirmation → executing → completed
任意非终态 → terminated；任意状态 → failed
```

方案生成不等于执行。只有用户确认当前方案后才锁定资源并进入执行（approve 直接落 executing，`approved` 为过路状态）；每次审批、重规划、轮次和状态变化都写入事件。反馈按 1 分钟内部模拟、5 分钟对外展示，关键事件可提前重规划。任务结束生成报告（在线查看 + 下载 JSON），扑灭归档时全员返航回收（RECOVERY）。审批带 `idempotency_key` 幂等；executing/approved/replanning 任务超 30 分钟无推进自动回收资源锁。

## 四、资源与调度（2+6+4）

初始虚拟资源为 R1–R2、E1–E6、S1–S4 十二架独立 UAV（S3/S4 为 multi_role 多用途支援机，计入灭火出动上限，前后端同口径上限 8，默认约束 4）。先过滤 `fault`、低健康度（<60）、低 SOC（<35% 新任务底线）、和药剂不兼容记录，再按 1..min(max_drones, 可参战数) 逐数量枚举组合评分，不默认全员出动。

编组分工（BE-14 落实冻结规则）：

- R1 全程主监测；火情 III 级+ 时 R2 加入「高风险复核侦察」；待充侦察机串行回充，全程至少 1 架 R 在线。
- S1/S2 双机分工：有人 → S1 通信广播/疏散引导、S2 照明与疏散路线复核；无人 → S1 物流补给/电池前送、S2 通信中继与后备侦察；unknown → S1 复核人员、S2 中继待命。
- 有人分支保留 1 架 E 作「疏散通道保护」（不投入压制组合，仍在出动名单）；人员不确定时限投（可战数 ≥2 时至少留 1 架机动）。
- 故障补位重过 SOC/健康/药剂模块/载荷/补给约束，名单原子同步（selected_uavs、firefighting_uavs、battery_plan、tasks、资源锁）。

当前 Store 为「内存工作态 + SQLite 写穿持久化」（`FIREOPS_DB_PATH` 可多实例隔离），重启可恢复；多用户认证未实现（演示口径）。

## 五、核心算法（统一分钟推进）

地图按 100 m² 网格展示，火情以 FLP（Fire Load Points）表示，不用固定"每小时灭多少平方米"口径。

**火情负荷**：`B_i = 10 × I_i × K_fuel × K_wind × K_slope`，`B_total = ΣB_i`；面积折算用研判比率 `area_per_flp`（禁止硬编码 180）。

**火势增长**（BE-13 后的唯一口径）：`growth_rate_per_hour` 是场景/观测层比例增长率，方案生成后只随新观测重规划更新，审批/重规划不得改变；每分钟 `FLP ← FLP × (1 + g/60) − 本分钟压制`（比率复利，分母是方案基线，余烬不自参照反弹）。

**药剂有效能力**：`S = Q_agent × κ(药剂,火型) × η_drop × η_weather`，全部读 `configs/simulation.json` 冻结段；每架无人机按自身 `payload_module` 计量——W20 计升（4 L/min）、C6 计千克（1.5 kg/min），消耗日志分键 `water_liters`/`co2_kg`，同一架次不混装。

**SOC 与可行性**：耗电率以 `%/h` 配置（飞行 270、作业 ×1.05、悬停 ×0.75、侦察 90），分钟核心逐步扣减；35% 新任务接单线 / 25% 返航硬约束 / 15% 应急；复飞双门槛（机上药剂 >0 且 SOC ≥25%）。方案必须满足药剂兼容、载荷、路线、健康度、SOC；不满足输出 `resource_gap`。

**调度与评分**：候选生成 → 硬约束过滤 → 统一分钟核心在状态副本上仿真（120 分钟视野）→ `J = 0.40T + 0.30B + 0.15E + 0.10M + 0.05N`（越小越优）→ 最优 + 备选（≤8 个）。输出 `can_control / control_verdict（can_control|maintain_only|cannot_control）`，不可控时给 `effective_flp` 真实缺口，不产虚假时间窗。

**闭环与重规划触发器**：`fire_load_increase_over_20_percent`（相对审批触发基线，≥20 FLP 绝对下限）、`wind_band_changed`、`soc_below_return_threshold`、`agent_insufficient`、`people_status_changed`、`signal_below_threshold`（BE-14）、`resource_or_soc`、`llm_judgment_replan`（GLM 建议需趋势闸门）。输出仿真时间区间，不使用"18 分钟"单点结论。

## 六、可替换适配器（现状）

```text
detect_fire       → YOLO/PWM-YOLO Adapter   【接收面就绪，真实权重待交付（E-1）】
analyze_with_vlm  → VLM Adapter             【glm-4.6v-flash 直连已上线 + 契约守卫】
extract_frames    → 路由层 OpenCV 抽帧       【MP4 上传自动抽帧（BE-11）】
get_environment   → Open-Meteo + OSM        【已接入，离线回退标注来源】
AnalysisStore     → SQLite 写穿             【已实现】
事件通知           → SSE                     【已实现，Last-Event-ID 断线续传；WebSocket 未做】
真实飞控 / 连续视频流 / 全国 GIS 全量 / 多用户权限              【未实现（有意排除）】
```

## 七、文档索引

契约：`api-contract.md` / `data-dictionary.md`；冻结规则与实现对照：`无人机子群与参数规则1.md`；需求与设计思路：`requirements.md`；能力边界：`压制能力与火情边界分析.md`；执行链路统一方案（BE-13）：`代码更正与执行链路统一方案.md`；协作与演示：`架构职责划分纪要.md` / `demo-script.md` / VLM·YOLO 手册。
