# CASE-009 测试记录（02_run_cases.py 自动生成）

- 生成时间: 2026-09-06 21:14:25
- 模型: glm-4.6v-flash | 提示词: v3 | temperature 0.1 / max_tokens 2048
- 说明: 本文件反映最近一次运行的档位；各档完整证据见 runs/ 子目录，历史见 logs/
- 场景: 电力线索+劣质图双测试：火点临近疑似电线杆（横担+多根线缆），画面偏模糊+顶部有遮挡物
- 图片: CASE-009-R1-F1=T09.jpg
- 人工核验依据: 2026-09-06人工核验：画面中上部较大明火+灰白烟向左上扩散；火点旁疑似电线杆（横担+线缆向左下延伸），下方有砖砌结构（不确定是否建筑，电力与建筑仅疑似、不设硬性预期检查）；整体偏模糊轻微失焦、顶部有浅色遮挡物（疑似屋檐/桥边）、火点过曝；未见人员/道路/水面

## Tier A-p3（A档：无YOLO（yolo_status=missing））

- 调用: HTTP 200 | 耗时 18.4s | 限流重试 0 次 | 格式修复重试 否
- tokens: prompt=2920 completion=1037 (reasoning=622)
- 结构检查: 未通过
  - [问题] 输出包含Markdown代码围栏(```)
- 禁止项扫描: 未发现
- 预期检查: 2/4 通过
  - [PASS] 火光仍可辨认→flame_observed：fire_observation.fire_presence eq flame_observed（实际 'flame_observed'）
  - [FAIL] 偏模糊+遮挡+过曝，画质不得评为good：image_quality.quality_level ne good（实际 'good'）
  - [FAIL] 质量问题须如实列出（模糊/遮挡/过曝至少一项）：image_quality.problems contains_any ['blurry', 'obstruction', 'overexposed']（实际 ['none']，命中 []）
  - [PASS] 单轮图片→first_round_no_comparison：smoke_trend.temporal_trend eq first_round_no_comparison（实际 'first_round_no_comparison'）
- 结论: **FAIL**
