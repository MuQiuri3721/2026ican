# 火巡智策 VLM 队员执行手册

> 智谱 GLM-4.6V-Flash 火场视觉分析准备与交付
> 登记日期：2026-09-05 · 对应追踪清单 E-2（VLM 独立解释服务交付）· 状态：已交付并接入上线（2026-09-06 交付 / 2026-09-07 BE-11 接入；§9 提交清单视为已核）

| 项目项 | 冻结内容 |
|---|---|
| 执行对象 | 负责 VLM 模型准备与验证的队员 |
| 交付对象 | 项目唯一开发者 |
| 当前条件 | 已有前端和规则仿真；PWM-YOLO 预计两天后就绪 |
| 首版模型 | 智谱标准 API：glm-4.6v-flash |
| 工作边界 | 准备模型、提示词、测试数据与样例；**不修改后端核心代码** |

**最终决定**：现在不等待 PWM-YOLO。VLM 队员先用原始火灾图片和明确标记为 fixture 的模拟 YOLO 结果完成模型验证；PWM-YOLO 就绪后，再替换成真实检测结果做联合测试。

---

## 1 这位队员最终要完成什么

这位队员的任务不是开发整套后台，也不是研究无人机调度算法，而是把视觉模型准备成一项**可交接能力**：开发者拿到模型名称、标准 API Key、冻结提示词、输入输出样例和测试结果后，可以直接接入现有侦察研判链。

- 确认免费视觉模型能够稳定接收单图和多图。
- 建立火场图片测试集，并为每组图片写清预期观察结果。
- 冻结只输出视觉事实的提示词和 `vlm-analysis-v1` 结构。
- 完成无 YOLO、模拟 YOLO、真实 YOLO 三种输入状态的测试。
- 把非敏感材料整理后上传 GitHub，向开发者完成交接。

## 2 模型、套餐与 API 使用口径

### 2.1 首版固定模型

首版模型：**glm-4.6v-flash**。智谱官方当前将其标注为完全免费，支持图像、文本等输入，满足本项目图片理解和结构化描述需求。

| 项目 | 采用口径 | 队员要做的事 |
|---|---|---|
| 模型供应商 | 智谱开放平台 | 不再比较 Kimi 或其他供应商 |
| 模型名称 | glm-4.6v-flash | 按该名称完成全部首版测试 |
| 调用入口 | 标准 API 地址 | 使用开放平台标准 API Key |
| 团队套餐 | 用于支持的编程工具和队员辅助工作 | **不要**把团队 Coding Plan Key 当成项目标准 API Key |
| 费用口径 | 当前免费，但仍受平台限流和政策约束 | 保存测试日期、模型名和调用状态 |

### 2.2 必须区分两种 Key

| Key 类型 | 用途 | 能否直接用于项目 |
|---|---|---|
| 团队 Coding Plan Key | 在智谱支持的编码工具中消耗团队套餐额度 | **不作为**自建系统的正式模型接口 |
| 标准 API Key | 通过 open.bigmodel.cn 标准接口调用视觉模型 | **可以**；本项目使用这一种 |

> **安全要求**：任何 Key 都不上传 GitHub，不写进测试截图，不放进 JSON 或 README。开发者最终通过环境变量配置 Key。

### 2.3 第一天先完成的账号检查

1. 登录智谱开放平台，确认自己已获得团队席位；团队席位用于协作和准备工作。
2. 进入标准 API 控制台，创建或确认一枚可用的标准 API Key。
3. 在体验中心用 glm-4.6v-flash 分析一张森林火灾图片，确认模型确实能看图。
4. 用标准 API 完成一次调用，记录模型名、请求时间、是否成功和响应时长。
5. 连续调用 5 次；5 次均成功后再进入提示词测试。

## 3 PWM-YOLO 未就绪期间怎么开展工作

当前阶段：只验证 VLM 视觉理解链，**不声称已经接入真实 PWM-YOLO**。所有模拟检测结果必须写 `mode=fixture`、`source=manual_fixture`。

### 3.1 建立三档输入

| 档位 | 输入内容 | 目的 | 结果标记 |
|---|---|---|---|
| A：纯图片 | 1—4 张按时间排序的火场图片 | 验证模型基础视觉理解 | `yolo_status=missing` |
| B：空检测 | 图片＋无目标的模拟 YOLO JSON | 验证 VLM 不会被空结果完全限制 | `mode=fixture` |
| C：有检测 | 图片＋人工制作的火焰/烟雾检测框 JSON | 验证 YOLO 结果能否约束 VLM 观察 | `mode=fixture` |

### 3.2 模拟 YOLO 文件写法

```json
{
  "schema_version": "yolo-observation-v1",
  "mode": "fixture",
  "source": "manual_fixture",
  "frame_id": "CASE-003-R0-F1",
  "detections": [
    {"class": "flame", "confidence": 0.88,
     "bbox_norm": [0.31, 0.42, 0.56, 0.73]}
  ]
}
```

坐标使用 0—1 归一化值；confidence 只是测试占位数，**不得写成 PWM-YOLO 真实预测**。PWM-YOLO 服务交付后，由开发者替换数据来源，字段语义不变。

### 3.3 PWM-YOLO 到位后的补测

1. 选择此前已经测试过的 5 组图片，取得 PWM-YOLO 真实返回结果。
2. 把 fixture JSON 替换为真实 YOLO JSON，保留同一提示词和同一 VLM 模型。
3. 对比纯图片、模拟检测、真实检测三种输出，记录变化。
4. 检查 VLM 是否修改或捏造 YOLO 置信度与检测框；如有，调整提示词。
5. 完成联合测试后才把状态从 `vlm-only` 改为 `yolo-vlm-integrated`。

## 4 VLM 输入、输出与禁止事项

### 4.1 每次提交给 VLM 的输入包

| 输入组 | 内容 | 没有时怎么处理 |
|---|---|---|
| 任务信息 | task_id、round_index、报警地点名称 | task_id 与 round_index **必须有** |
| 图片 | frame_id、拍摄顺序、时间、URL 或 Base64 | 图片不可读则停止本批次 |
| 相机信息 | 无人机编号、高度、朝向、镜头信息 | 未知字段写 null |
| YOLO 结果 | 火焰/烟雾类别、框、置信度 | 当前阶段允许 missing 或 fixture |
| 环境摘要 | 林地类型、坡度等级、天气与水源摘要 | 地理队员未交付前使用 demo 摘要 |
| 上一轮分析 | 上一次 VLM 结构化结果 | 首轮写 null |

### 4.2 VLM 固定输出

| 字段组 | 主要字段 | 作用 |
|---|---|---|
| 身份来源 | schema_version、task_id、round_index、mode、source | 证明结果来自哪个模型与批次 |
| 图片质量 | usable、quality_level、problems、missing_inputs | 决定是否需要补拍 |
| 火情观察 | fire_presence、affected_layer、canopy_involvement、visual_scale | 描述画面，**不计算 FLP** |
| 烟雾趋势 | smoke_density、image_plane_drift、temporal_trend | 描述图像变化，不等同气象风 |
| 对象线索 | people、road、building、power_equipment、water、obstacle | 向后端提供线索 |
| 复核信息 | conflicts、manual_review_required、human_summary | 提示冲突与不确定性 |

### 4.3 VLM 绝对不能输出的内容

- FLP、fire_cells、真实火场平方米面积和火势增长率。
- 实际风速、实际地理风向；烟雾在画面中的移动只能写 `image_plane_drift`。
- 无人机数量、具体无人机任务、悬停高度、SOC 消耗和飞行路线。
- W20、CO₂ 或其他药剂需求量、灭火效率和控制时间。
- "一定无人""一定有可用水源"等超出图像证据的结论。

> **判断边界**：没有看到人员只能写 `people.state=not_observed`，不能写 `absent`；看到水面只能写 `water_candidate`，能否取水由 GIS 和规则引擎判断。

## 5 提示词冻结与测试方法

### 5.1 系统提示词 V1

```text
你是森林火灾侦察视觉分析模块。你只负责从给定图片、PWM-YOLO 检测结果和环境摘要中
提取可见事实、趋势、冲突与不确定性。仅输出符合 vlm-analysis-v1 的 JSON，不输出
Markdown。禁止计算或编造 FLP、火场平方米面积、风速、增长率、无人机数量、药剂量、
SOC、路线和完成时间。未看到人员只能写 not_observed，不能写 absent。视觉水体只能
写 water_candidate。图像证据不足时写 uncertain 并列出 missing_inputs。不得修改输
入中的传感器、GIS 或 PWM-YOLO 数值。human_summary 只能复述结构化观察，不得新增
数字或行动指令。
```

### 5.2 用户消息模板

```text
任务：分析第{round_index}轮火场图片，并与上一有效轮次比较。
图片顺序：{frame_ids_with_time}
PWM-YOLO结果：{yolo_json}
相机与无人机元数据：{camera_json}
地理环境摘要：{scene_context_json}
气象观测：{weather_json}
上一轮分析：{previous_vlm_summary_or_null}
请严格按vlm-analysis-v1输出。
```

### 5.3 调参规则

| 参数/行为 | 冻结设置 |
|---|---|
| temperature | 0 或模型支持的最低稳定值 |
| 输出格式 | 只允许 JSON；不允许 Markdown 代码围栏 |
| 图片数量 | 首轮 1—3 张；时间对比 2—4 张 |
| 非法 JSON | 记录原始结果；允许一次"只修复 JSON 格式"的重试 |
| 第二次失败 | 本案例标记 failed，**不人工修改成成功样例** |
| 提示词版本 | 每次修改递增 prompt_version 并保留修改原因 |

> **禁止做法**：不要为了让结果看起来好而手工改写模型返回 JSON。人工预期结果和模型实际结果必须分别保存。

## 6 测试集与验收记录

### 6.1 最小测试集

先准备 **12 组案例、约 20—30 张图片**。图片优先从 PWM-YOLO 对应数据集的可公开使用样本中选取；若许可不明确，只保存文件清单、来源和哈希，不把整套数据上传公共仓库。

| 编号 | 场景 | 最少数量 | 核心检查 |
|---|---|---|---|
| T01 | 明显火焰＋烟雾 | 1 组 | fire_presence 与 smoke_density |
| T02 | 只有烟雾或疑似烟雾 | 1 组 | 不得凭空确认明火 |
| T03 | 普通森林、无火情 | 1 组 | 不得误报 |
| T04 | 图片模糊、过暗或遮挡 | 1 组 | usable 与 missing_inputs |
| T05 | 画面中存在人员线索 | 1 组 | people.state 与证据位置 |
| T06 | 画面中未观察到人员 | 1 组 | 必须是 not_observed |
| T07 | 疑似道路或建筑 | 1 组 | scene_elements |
| T08 | 疑似设备/电气热点 | 1 组 | 只输出线索 |
| T09 | 疑似水面 | 1 组 | 只能 water_candidate |
| T10 | 前后火势增强 | 1 组 | temporal_trend |
| T11 | 前后火势减弱 | 1 组 | temporal_trend |
| T12 | 前后变化不明确 | 1 组 | uncertain 而非强行判断 |

### 6.2 每个案例必须保存什么

```
CASE-001/
├── images/                 # 1—4 张图片
├── metadata.json           # 时间、顺序、相机信息
├── expected.json           # 人工预期观察
├── mock_yolo.json          # 当前为 fixture
├── request.json            # 去除 Key 后的请求
├── raw_response.json       # 模型原始返回
└── review.md               # 是否通过、问题与结论
```

## 7 GitHub 交付结构与上传规则

### 7.1 建议工作分支与目录

分支：使用 `docs/vlm-preparation`。只提交 VLM 准备材料和获准公开的测试数据，**不修改开发者负责的后端核心代码**。

```
docs/vlm-delivery/
├── README.md
├── model-selection.md
├── prompt-v1.md
├── api-call-example.md
├── evaluation-results.md
└── handoff-checklist.md

data/vlm-testcases/
├── cases.json
├── CASE-001/
├── CASE-002/
└── ...
```

### 7.2 每个文件写什么

| 文件 | 必须包含 |
|---|---|
| README.md | 任务范围、模型名、测试日期、目录说明 |
| model-selection.md | glm-4.6v-flash、标准 API、免费状态和验证结论 |
| prompt-v1.md | 系统提示词、用户模板、版本记录 |
| api-call-example.md | 去除 Key 的单图、多图请求与响应 |
| evaluation-results.md | 逐案例通过情况、响应时间、失败原因 |
| handoff-checklist.md | 交给开发者的模型、Key、字段和问题清单 |
| cases.json | 案例编号、图片文件、来源、许可、预期结果和状态 |

### 7.3 绝对不能上传

- 标准 API Key、团队套餐 Key、Authorization 请求头或 .env 文件。
- 带有账户余额、团队成员、手机号或个人信息的截图。
- 没有公开许可的数据集全集、私人现场图片或来源不明图片。
- 把 fixture 结果写成 real，或把人工框说成 PWM-YOLO 真实输出。

## 8 时间安排、验收标准与开发交接

### 8.1 立即执行计划

| 时间 | 主要任务 | 当日交付 |
|---|---|---|
| 第 1 天上午 | 确认标准 API Key；跑通 glm-4.6v-flash 单图与多图 | 5 次成功记录＋去密钥调用样例 |
| 第 1 天下午 | 按冻结 Schema 测试提示词；完成前 6 组案例 | prompt-v1＋6 组原始响应 |
| 第 2 天上午 | 完成 12 组测试集和 fixture YOLO | cases.json＋expected/mock_yolo |
| 第 2 天下午 | 统计 JSON 合规、禁止项、人员与水源边界 | evaluation-results 初稿 |
| 第 3 天 | 修订提示词、复测、整理 GitHub 目录并交接 | VLM 准备包 V1 |
| PWM-YOLO 就绪后 0.5—1 天 | 用 5 组相同图片替换真实检测结果联合测试 | yolo-vlm 联合测试记录 |

### 8.2 VLM 准备包通过标准

| 验收项 | 通过标准 |
|---|---|
| 基础可用 | 标准 API 连续 5 次调用成功；单图、多图均有合法返回 |
| 结构化输出 | 12 组案例中至少 11 组第一次或格式修复后得到合法 JSON |
| 安全边界 | 12 组均不输出 FLP、面积、风速、药剂量、无人机数量和时间 |
| 人员口径 | 所有"未观察到人员"案例均输出 not_observed，不出现 absent |
| 水源口径 | 视觉水面只标记 water_candidate，不判断可取水 |
| 劣质图片 | 模糊/遮挡案例能输出 usable=false 或明确 missing_inputs |
| 时序分析 | 增强、减弱、不明确三类案例均给出对应或保守结果 |
| 可追溯 | 每条结果保留模型名、prompt_version、image_ids 和测试时间 |
| 保密 | GitHub 扫描不到任何 Key 或账户信息 |

### 8.3 向开发者交接时必须说清楚

- 正式使用的模型为 glm-4.6v-flash，调用使用标准 API Key。
- 哪一版提示词已经冻结，哪些字段仍可能不稳定。
- 单图、多图、Base64 或 URL 分别如何调用。
- 平均响应时间、最长响应时间、失败类型和重试情况。
- 哪些测试结果来自 fixture，哪些来自真实 PWM-YOLO。
- API Key 通过私下渠道交付，只告诉开发者对应环境变量名称。

> **完成定义**：开发者不需要重新替队员做模型选择、提示词试验和样本整理；拿到交付包后，只需实现 VLMClient、Schema 校验、融合逻辑、存储和前端展示。

## 9 最终提交清单

| 状态 | 交付物 | 文件/证据 |
|---|---|---|
| □ | 标准 API 已跑通 | 5 次连续调用记录 |
| □ | 模型已冻结 | glm-4.6v-flash |
| □ | 提示词已冻结 | prompt-v1.md |
| □ | 输出结构已验证 | vlm-analysis-v1 样例 |
| □ | 12 组案例已完成 | cases.json 与各 CASE 目录 |
| □ | 模拟 YOLO 已明确标记 | mode=fixture/source=manual_fixture |
| □ | 测试报告已完成 | evaluation-results.md |
| □ | GitHub 无敏感信息 | 提交前 Key 扫描结果 |
| □ | 开发者已完成接收确认 | handoff-checklist.md |
| □ | PWM-YOLO 联合测试已排期 | 模型到位后的测试日期 |

## 10 官方口径与版本说明

截至 2026 年 9 月 5 日，智谱官方文档将 GLM-4.6V-Flash 标注为完全免费，并说明 GLM-4.6V 系列支持图像与文本输入。与此同时，GLM Coding Plan 官方 FAQ 明确说明，套餐额度仅用于官方支持的指定工具和产品环境；自建应用应使用标准 API 服务。若平台后续调整模型名称、免费政策或限流规则，以调用当天控制台和官方文档为准。

官方文档：

1. <https://docs.bigmodel.cn/cn/guide/models/vlm/glm-4.6v>
2. <https://docs.bigmodel.cn/cn/coding-plan/faq>

---

**一句话任务**：先把 glm-4.6v-flash、提示词、12 组测试案例和标准 JSON 准备好；PWM-YOLO 到位后只补联合测试，不重新推倒 VLM 方案。
