# CASE-002 测试记录（02_run_cases.py 自动生成）

- 生成时间: 2026-09-06 21:54:56
- 模型: glm-4.6v-flash | 提示词: v4 | temperature 0.1 / max_tokens 2048
- 说明: 本文件反映最近一次运行的档位；各档完整证据见 runs/ 子目录，历史见 logs/
- 场景: 只见浓烟不见明火（防幻觉关键案例）：灰白浓烟弥漫，画面中无火苗
- 图片: CASE-002-R1-F1=T02.jpg
- 人工核验依据: 2026-09-06人工核验：画面仅浓烟（灰白为主，局部深灰），未见任何火苗/火光，无人员/道路/建筑/电力设备/水面，画质清晰

## Tier C-p4（C档：fixture含人工框（mode=fixture, source=manual_fixture））

- 调用: HTTP 429 | 耗时 296.4s | 限流重试 4 次 | 格式修复重试 否
- 错误: 限流(429)，重试4次后仍失败 | 该模型当前访问量过大，请您稍后再试
- 结构检查: 未通过
  - [问题] JSON无法解析: None
- 禁止项扫描: 未发现
- 预期检查: 0/4 通过
  - [FAIL] 只看到烟→smoke_only（禁止凭烟报flame_observed）：fire_observation.fire_presence in ['smoke_only', 'uncertain']（模型输出未解析）
  - [FAIL] 烟量中等或浓：smoke_trend.smoke_density in ['medium', 'heavy']（模型输出未解析）
  - [FAIL] 画面无人员→not_observed：object_clues.people.state eq not_observed（模型输出未解析）
  - [FAIL] 单轮图片→first_round_no_comparison：smoke_trend.temporal_trend eq first_round_no_comparison（模型输出未解析）
- 结论: **FAILED_API**
