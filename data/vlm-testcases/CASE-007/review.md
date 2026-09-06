# CASE-007 测试记录（02_run_cases.py 自动生成）

- 生成时间: 2026-09-06 21:33:07
- 模型: glm-4.6v-flash | 提示词: v3 | temperature 0.1 / max_tokens 2048
- 说明: 本文件反映最近一次运行的档位；各档完整证据见 runs/ 子目录，历史见 logs/
- 场景: 保护目标线索：右侧远处火线+浓烟遮蔽上半部，左下角可见红屋顶建筑一角
- 图片: CASE-007-R1-F1=T07.jpg
- 人工核验依据: 2026-09-06人工核验：右侧远处橙色火线沿地平线横向蔓延，棕黑/灰黄浓烟占画面上半部；左下角红屋顶建筑一角（部分被树木遮挡）；未见人员/道路/电力设备/水面；清晰度尚可，上半部受烟遮挡

## Tier B-p3（B档：空fixture（detections=[]，验证空结果不阻断观察））

- 调用: HTTP 200 | 耗时 28.1s | 限流重试 0 次 | 格式修复重试 否
- tokens: prompt=1421 completion=1330 (reasoning=848)
- 结构检查: 未通过
  - [问题] 输出包含Markdown代码围栏(```)
- 禁止项扫描: 未发现
- 预期检查: 7/7 通过
  - [PASS] 能认出远处火线明火：fire_observation.fire_presence eq flame_observed（实际 'flame_observed'）
  - [PASS] 烟量中等或浓：smoke_trend.smoke_density in ['medium', 'heavy']（实际 'heavy'）
  - [PASS] 红屋顶建筑可见→observed：object_clues.building.state eq observed（实际 'observed'）
  - [PASS] 建筑证据非空（位置/颜色）：object_clues.building.evidence nonempty （实际 '画面左下角可见红色屋顶建筑'）
  - [PASS] 画面无人员→not_observed：object_clues.people.state eq not_observed（实际 'not_observed'）
  - [PASS] 单轮图片→first_round_no_comparison：smoke_trend.temporal_trend eq first_round_no_comparison（实际 'first_round_no_comparison'）
  - [PASS] 空fixture不得阻断观察：仍应报明火：fire_observation.fire_presence ne none_observed（实际 'flame_observed'）
- 结论: **FAIL**
