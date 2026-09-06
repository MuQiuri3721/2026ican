# CASE-001 测试记录（02_run_cases.py 自动生成）

- 生成时间: 2026-09-06 22:00:15
- 模型: glm-4.6v-flash | 提示词: v4 | temperature 0.1 / max_tokens 2048
- 说明: 本文件反映最近一次运行的档位；各档完整证据见 runs/ 子目录，历史见 logs/
- 场景: 明显明火+浓烟：地表火带蔓延，另有一棵树整株燃烧（树冠卷入迹象）
- 图片: CASE-001-R1-F1=T01.jpg
- 人工核验依据: 2026-09-06人工核验：多点火焰沿地表蔓延+一棵树自底至顶燃烧，浓烟，画面中无人员/道路/建筑/电力设备/水面，画质清晰

## Tier A-p4（A档：无YOLO（yolo_status=missing））

- 调用: HTTP 200 | 耗时 318.3s | 限流重试 4 次 | 格式修复重试 否
- tokens: prompt=2249 completion=1462 (reasoning=1039)
- 结构检查: 通过
- 禁止项扫描: 未发现
- 预期检查: 5/5 通过
  - [PASS] 能认出明火：fire_observation.fire_presence eq flame_observed（实际 'flame_observed'）
  - [PASS] 有树冠卷入迹象（画面可见整树燃烧）：fire_observation.canopy_involvement in ['observed', 'uncertain']（实际 'observed'）
  - [PASS] 烟量中等或浓：smoke_trend.smoke_density in ['medium', 'heavy']（实际 'heavy'）
  - [PASS] 画面无人员→not_observed：object_clues.people.state eq not_observed（实际 'not_observed'）
  - [PASS] 单轮图片→first_round_no_comparison：smoke_trend.temporal_trend eq first_round_no_comparison（实际 'first_round_no_comparison'）
- 结论: **PASS**
