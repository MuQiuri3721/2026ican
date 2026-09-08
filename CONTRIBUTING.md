# 开发规范（CONTRIBUTING）

> 适用范围：森林火灾救援智能体（2026ican）全部代码、数据、文档与演示材料。
> 本文件是团队协作的唯一流程规范；接口字段的唯一权威是 [docs/api-contract.md](docs/api-contract.md)。
> 最近更新：2026-09-04。

## 1. 文档权威顺序

同一问题多处文档冲突时，按以下顺序取用，越靠前越权威：

1. `docs/api-contract.md` —— 接口、字段、单位、错误码、模型接入协议的唯一权威；
2. `docs/无人机子群与参数规则1.md` —— 冻结的仿真参数与业务规则 V1；
3. `README.md`、`docs/architecture.md`（含算法与 Agent 分层）、`docs/data-dictionary.md` —— 与代码同步维护的现状文档；
4. `docs/task-progress.md` —— 进度与验收口径；
5. `docs/无人机规则落地实施规划.md` —— 实施规划，阶段状态以其"当前实现状态"小节为准；
6. `docs/实现差异审计.md` —— 2026-09-03 的审计快照，只作历史参考，不随代码更新；
7. `森林火灾救援智能体项目方案.md` —— **历史立项存档**。其中的"无人机一/二/三""80 kg 水剂""18 分钟""drone-1/2/3""simulation.yaml"等均为旧口径示例，已被第 2 节的冻结口径取代，仅作背景阅读，禁止作为开发依据。

`docs/requirements.md` 是需求与设计思路文档：业务流程与交互原则有效，具体接口/文件名以 api-contract.md 为准。

## 2. 统一冻结口径

以下口径已在 `docs/无人机子群与参数规则1.md` 冻结，任何代码、文档、前端文案不得再引入与之冲突的表述：

| 项 | 冻结口径 | 禁止出现的旧口径 |
|---|---|---|
| 资源池 | 2+4+2 八架独立 UAV：R1–R2 侦察、E1–E4 灭火、S1–S2 支援，按需动态出动 | 固定三架、DR-01/02/03、drone-1/2/3 |
| 火情度量 | FLP 负荷（100 m² 网格展示），`B_i = 10×I×K_fuel×K_wind×K_slope` | 固定"平方米/小时"灭火能力 |
| 药剂 | W20 水剂用于植被火；C6 CO₂ 仅用于局部设备/电气热点；同一架次不混装 | "携带 80 kg 水剂"等旧示例 |
| 电量 | SOC 按 1 分钟内部步长折算，预计返航 SOC ≥ 25% | 整小时结算 |
| 时间输出 | 仿真时间区间（`estimated_control_time.window_minutes`）或资源缺口 | "18 分钟"单点结论 |
| 执行门禁 | 方案生成 ≠ 执行；必须 `approve` 后锁定资源进入 `executing` | 分析完成即执行 |
| 环境来源 | 真实/演示来源必须标注 `mode`/`source`，失败回退标记 `demo-fallback`/`stale` | 把 fallback 说成真实数据 |

历史文档（第 1 节第 7 条）保留旧口径原文不改写，但必须保留顶部的口径更新声明；新写的任何材料引用历史示例时必须注明"历史方案示例，已被 V1 口径取代"。

## 3. 开发者分工

> 2026-09-04 起：平台编码由两位开发者并行推进，按"域"垂直切分，**不共享任何代码文件**（所有权表见第 4 节）；YOLO/VLM 等模型能力由外部成员交付，不进入本仓库编码。

### 开发者 A：任务链路与规则引擎（后端核心域）

默认人选：马其瑞 / muqiuri（A/B 标签可由两人自行对调，对调后同步更新本节）。

- 应用装配与任务路由：`backend/app/main.py`、`backend/app/routes/task_routes.py`；
- 任务生命周期：`backend/app/domain/`、`backend/app/services/analysis_service.py`；
- 智能体分层：`backend/app/agents/`、`backend/app/skills/`、`backend/app/tools/base.py`、`tools/registry.py`、`tools/core.py`、`backend/app/pipeline.py`；
- 数据与配置：`data/scene.json`、`data/fleet.json`、`data/inventory.json`、`data/vision_observations.json`、`configs/simulation.json`；
- 契约与测试：`tests/`（契约、规则、场景、适配器测试）、`docs/api-contract.md`（双人冻结）、`docs/data-dictionary.md`、`docs/task-progress.md`、`docs/architecture.md`；
- 后端侧联调、发布门禁与验收记录。

### 开发者 B：环境态势与指挥工作台（前端 + 环境域）

- 前端全部：`frontend/src/`（含 App.vue、样式）、`frontend/vite.config.js`、`frontend/index.html`、`frontend/README.md`；
- 环境与地理后端：`backend/app/services/environment_service.py`、`environment_cache.py`、`terrain_service.py`、`backend/app/tools/environment.py`、`backend/app/routes/environment_routes.py`；
- 环境侧测试：`tests/test_environment*.py`（新增归 B）；
- 展示与演示文档：`docs/requirements.md`、`docs/demo-script.md`；
- 前端侧联调、浏览器验收与演示录制。

两个域的合法交集只有两个冻结文档（第 6.2 节）和一处低频注册点：B 新增环境 Tool 时需要在 A 所有的 `tools/registry.py` 注册，由 A 执行（一次性改动，提前在群里说明即可）。

### 外部模型协作（不修改本仓库代码）

- 听日：YOLO/PWM-YOLO——独立 HTTP 检测服务，按 `docs/api-contract.md` 第 9 节协议通过 `FIRE_YOLO_ENDPOINT` 接入；权重、训练脚本与 `yolo/README.md` 放在仓库外或 `yolo/` 目录；
- 吉相如：VLM/LLM——独立服务 + `FIRE_VLM_ENDPOINT` 协议（api-contract.md 第 10 节）；
- 两者需要新字段时，在 api-contract.md 提契约变更申请，由 A 实现接入；平台不以模型服务存在为前提保持可运行；
- 江月：总体需求、Word/PDF 方案与进度；杨涵：地理/环境数据核对（产出交 B 合入环境域，或交 A 合入 data fixture）。

## 4. 文件与目录单一负责人

每个文件只有一个负责人，**两人之间不存在共享的代码文件**；改动不属于自己负责的文件，必须先在群里说明并获负责人确认。

| 路径 | 负责人 | 备注 |
|---|---|---|
| `backend/app/main.py` | A | 仅应用装配：CORS 与路由挂载 |
| `backend/app/routes/task_routes.py` | A | 任务/平台路由 |
| `backend/app/routes/environment_routes.py` | B | 环境/等高线路由 |
| `backend/app/domain/`、`services/analysis_service.py` | A | 契约与任务用例，变更需同步 api-contract.md |
| `backend/app/skills/`、`agents/`、`pipeline.py` | A | 确定性规则唯一来源 |
| `backend/app/tools/base.py`、`registry.py`、`core.py` | A | core 含 YOLO/VLM 适配协议实现 |
| `backend/app/tools/environment.py`、`services/environment_service.py`、`environment_cache.py`、`terrain_service.py` | B | 环境与地理域 |
| `frontend/src/`、`frontend/vite.config.js`、`frontend/index.html` | B | App.vue 为单文件，仅 B 编辑 |
| `data/*.json`、`configs/*.json` | A | 视同契约文件，见第 6.3 节 |
| `tests/test_contracts.py`、`test_rules.py`、`test_scenarios.py`、`test_adapters.py` | A | 契约测试是变更门禁 |
| `tests/test_environment*.py` | B | 环境域测试 |
| `docs/api-contract.md`、`CONTRIBUTING.md`、`docs/无人机子群与参数规则1.md` | 双人冻结 | 修改需两人确认（6.2） |
| `docs/architecture.md`（含算法/Agent 分层）、`data-dictionary.md`、`task-progress.md` | A | 与后端代码同步 |
| `docs/requirements.md`（含设计思路）、`demo-script.md` | B | 需求展示与演示流程 |
| `yolo/`（权重、脚本、yolo/README.md） | 外部（听日） | 不进入后端运行链 |
| `森林火灾救援智能体项目方案.md`、`docs/实现差异审计.md` | 冻结 | 历史存档，只加声明不改写 |

## 5. 分层职责（Schema / Tool / Skill / Service / UI）

| 层 | 只负责 | 禁止 |
|---|---|---|
| `domain/schemas.py` | Pydantic 契约、枚举校验、单位约束 | 携带业务计算逻辑 |
| `tools/` | 单一、确定性、可复算的查询或计算，统一 `ok/tool/source/data/error` 信封 | 依赖其他 Tool 的执行结果产生副作用；引入随机性 |
| `skills/` | 按业务步骤组合 Tool、传递结构化上下文、处理有人/无人分支 | 绕过 Tool 直接算安全关键数字 |
| `services/` + `domain/store.py` | 任务状态机、方案版本、审批、资源锁、轮次、报告持久化 | 在锁外修改任务状态；允许多个任务用例入口 |
| `pipeline.py` | 兼容入口与确定性演示管线；`deterministic_v1_dispatch` 是调度唯一算法源 | 在 Skill/前端重复实现第二套调度 |
| `main.py` + `routes/` | 路由、输入校验、HTTP 错误映射、CORS（A 管任务域，B 管环境域） | 业务逻辑内联 |
| UI（`frontend/src/`） | 展示、表单、确认/拒绝/终止操作 | 自行推导 FLP、SOC、数量、时间等业务数字 |

**红线**：任何大模型/VLM 输出不得覆盖 FLP、SOC、药剂需求、无人机数量、完成时间等安全关键数字；模型只允许输出观察与解释。

## 6. API 契约冻结规则

### 6.1 契约变更流程

1. 先改 `docs/api-contract.md`（写清新字段、单位、默认值、错误码）；
2. 再改/加 `tests/test_contracts.py` 契约测试；
3. 最后改实现代码；
4. 三者必须出现在同一次提交或同一 PR 中，不允许"代码先上、文档后补"。

### 6.2 冻结文件

`docs/api-contract.md` 与 `docs/无人机子群与参数规则1.md` 为双人冻结文件：修改需两位开发者都确认（评论/群内回执即可）。已发布给外部模型协作成员的协议（api-contract.md 第 9 节 YOLO、第 10 节 VLM）只增不破：新增字段必须可选，删除/改名字段必须保留一个兼容周期。

### 6.3 数据文件视同契约

`data/scene.json`、`data/fleet.json`、`data/inventory.json`、`data/vision_observations.json`、`configs/simulation.json` 的字段变更按 6.1 流程走，并在 api-contract.md 的数据小节登记。

### 6.4 schema_version 规范

- 领域对象必须带 `schema_version`，命名 `对象名-vN`：`uav-v1`、`fleet-v1`、`inventory-v1`、`analysis-v1`、`uav-dispatch-v1`；
- 工具型/辅助接口（health、environment、terrain、tools、skills、events、rounds）不强制携带；
- 字段语义破坏性变更时递增版本号，并保留旧版本一个兼容周期。

## 7. Git 分支与提交规范

- `main` 为受保护主分支：只接受"测试门禁全绿"的提交进入；禁止 force push。
- 功能分支命名：`feat/<scope>-<desc>`、`fix/<scope>-<desc>`、`docs/<desc>`、`yolo/<desc>`；scope 取 backend / frontend / data / tests。
- 提交信息：祈使句、主题行 ≤ 72 字符（延续现有英文风格，如 `Implement UAV dispatch and closed-loop workflow`）；一次提交只做一件事；契约、实现、测试同步变更时放在同一提交。
- **修改登记**：所有非琐碎修改开工前登记到 [docs/修改追踪清单.md](docs/修改追踪清单.md)（ID、涉及文件、验收标准），完成后更新状态并填入验证方式；禁止只改代码不改清单。
- 提交前必须本地通过（见第 9 节门禁），失败不允许提交。
- 单文件改动前先 `git pull --rebase`，减少并行冲突。

## 8. 并行开发规则

- 两位开发者各自只修改第 4 节所有权表中自己名下的文件，**天然无同文件冲突**；确需跨域修改时，先沟通认领，认领期间该文件由认领者独占并在群里声明。
- 双人接触点只有冻结文档（api-contract.md、CONTRIBUTING.md、规则 V1，均按 6.2 确认）与一处低频注册点：B 新增环境 Tool 需要登记进 A 所有的 `tools/registry.py`，由 A 执行。
- 数据/配置文件（A 所有）变更提前在群里预告，避免演示前 48 小时内做契约级变更。
- 遇到对方域的改动导致自己域测试失败：不在对方文件上直接"顺手修复"，通知负责人处理；纯契约同步（第 6.1 条）除外。
- 联调节奏建议：A 的路由/契约变更合入 main 后，B 的前端以最新 main 为基线拉分支，避免基于过期契约开发。

## 9. 测试、联调与发布门禁

每次提交前本地必须全绿：

```bash
pytest -q
python -m py_compile backend/app/main.py backend/app/pipeline.py
cd frontend && npm run build
```

联调启动：

```bash
uvicorn backend.app.main:app --reload --port 8000   # 后端
cd frontend && npm run dev                           # 前端 http://localhost:5173
```

发布（演示/交付）前额外完成浏览器六场景验收：

1. 紫金山一般林地、无人：R 监测 + 若干 E 灭火 + S 物流；
2. 确认有人：S 通信/指引，保留 E 保护疏散通道；
3. 第二轮风速升档：触发重规划并生成新方案版本；
4. SOC 不足：返航并启用换电/备机；
5. 库存不足：输出补给与资源缺口；
6. 拒绝/调整方案：资源释放或新方案版本正确。

验收结果记录到 `docs/task-progress.md` 的交付验收口径小节。

## 10. 数据来源、单位、版本与错误码规范

- **来源标注**：环境/视觉结果必须带 `mode`（demo / real / demo-fallback）、`source`，失败时附 `fallback.code`；真实查询失败允许 stale 返回但必须置 `stale: true`。`offline` 是请求模式，结果里体现为 `mode=demo` + `metadata.network=disabled`。
- **单位**：SOC/信号/健康度 %；载荷与药剂容量 kg；药剂余量 W20 为 L、C6/SUP10 为 kg；速度 m/s；耗电 %/h；风速 m/s；距离 m；面积 m²（展示）与 FLP（内部）；控制时间 min；时间戳 ISO 8601。新增字段必须带单位后缀（`_m2`、`_mps`、`_minutes`、`_m`、`_kg`、`_liters`）。
- **坐标**：任务内所有 `x/y`（`fleet.position`、`scene.fire_origin`、水源 `position`）共用同一套演示相对坐标（米），距离计算只在此坐标系内进行；GPS 参考值单独存放（`fire_origin_gps`、视觉 `fire_center` 的 `latitude/longitude`），只用于展示与环境查询，环境查询一律使用 `latitude/longitude`（见 api-contract.md §1.3）。新增距离类功能必须沿用该口径。
- **错误码**：HTTP 层 404（不存在）/ 409（状态冲突、资源被锁、过期方案、轮次倒退、终态操作）/ 413（上传超限）/ 415（类型不符）/ 422（参数校验）/ 502（Skill 链失败）；Tool 层错误码 `code`（如 `scene_not_found`、`invalid_input`、`detector_unavailable`）以 api-contract.md 错误码表为准，新增错误码先登记再使用。

## 11. 冲突解决与回滚

- 合并冲突按优先级取值：api-contract.md > 契约测试 > 后端实现 > 前端 > 其他文档。
- 提交历史保持线性：`pull --rebase` 后推送；不可避免的历史分叉由负责人 rebase。
- 回滚使用 `git revert`（保留历史），禁止 rewrite 已推送提交。回滚后端行为时必须同时确认 `data/reports/` 中已归档报告未被半途破坏；**禁止只回滚前端而保留已变更的后端状态**。
- 演示前的紧急修复遵循：最小 diff → 门禁全绿 → 群内同步 → 提交。

## 12. 当前实现边界（对外表述规范）

在 README、演示、答辩与文档中，只允许声明以下为"已实现"：

- 2+4+2 资源池、确定性规则链、审批闭环、5 分钟反馈重规划、报告归档、紫金山环境查询（含离线回退）、契约测试与前端构建。

必须明示"当前为演示实现"的部分：

- 视觉为 fixture/适配器（`detect_fire` 未配置端点时返回 fixture）；
- 执行为规则仿真（不连接真实飞控）；
- 路线为演示模型（非生产级避障）。

`AnalysisStore` 已使用 SQLite 写穿持久化（`data/analysis_store.db`，git 忽略；删除该文件即重置演示状态），重启后任务、事件与资源锁可恢复。

禁止表述："真实 YOLO/VLM 已接入""已连接真实无人机""全部方案已实现"。YOLO/VLM 服务接入后，表述必须能给出 `mode/source` 证据；未配置端点时不得把 fallback 称为真实模型结果。
