# CASE-003 测试记录（02_run_cases.py 自动生成）

- 生成时间: 2026-09-06 20:54:13
- 模型: glm-4.6v-flash | 提示词: v3 | temperature 0.1 / max_tokens 2048
- 说明: 本文件反映最近一次运行的档位；各档完整证据见 runs/ 子目录，历史见 logs/
- 场景: 无火纯森林（防误报）：茂密阔叶林航拍，画面无火无烟。C档故意给『假火焰框』测矛盾上报
- 图片: CASE-003-R1-F1=T03.jpg
- 人工核验依据: 2026-09-06人工核验：健康茂密阔叶林航拍，无火无烟，无人工设施，画质清晰；注意图带『昵享网』水印

## Tier A-p3（A档：无YOLO（yolo_status=missing））

- 调用: HTTP 200 | 耗时 331.9s | 限流重试 4 次 | 格式修复重试 否
- tokens: prompt=2340 completion=1560 (reasoning=1117)
- 结构检查: 通过
- 禁止项扫描: 未发现
- 预期检查: 2/2 通过
  - [PASS] 无火不得误报：fire_observation.fire_presence eq none_observed（实际 'none_observed'）
  - [PASS] 无烟或极淡：smoke_trend.smoke_density in ['none', 'light']（实际 'none'）
- 结论: **PASS**

## Tier B-p3（B档：空fixture（detections=[]，验证空结果不阻断观察））

- 调用: HTTP 200 | 耗时 163.9s | 限流重试 3 次 | 格式修复重试 否
- tokens: prompt=2362 completion=1170 (reasoning=778)
- 结构检查: 未通过
  - [问题] smoke_trend.image_plane_drift取值非法: 'first_round_no_comparison'
- 禁止项扫描: 未发现
- 预期检查: 2/2 通过
  - [PASS] 无火不得误报：fire_observation.fire_presence eq none_observed（实际 'none_observed'）
  - [PASS] 无烟或极淡：smoke_trend.smoke_density in ['none', 'light']（实际 'none'）
- 结论: **FAIL**

## Tier C-p3（C档：故意错误的fixture（画面无火却给火焰框，测矛盾上报））

- 调用: HTTP 200 | 耗时 42.4s | 限流重试 1 次 | 格式修复重试 否
- tokens: prompt=2401 completion=1428 (reasoning=996)
- 结构检查: 未通过
  - [问题] smoke_trend.image_plane_drift取值非法: 'first_round_no_comparison'
- 禁止项扫描: 未发现
- 预期检查: 4/4 通过
  - [PASS] 无火不得误报：fire_observation.fire_presence eq none_observed（实际 'none_observed'）
  - [PASS] 无烟或极淡：smoke_trend.smoke_density in ['none', 'light']（实际 'none'）
  - [PASS] 不被假YOLO带偏：仍判定无火：fire_observation.fire_presence eq none_observed（实际 'none_observed'）
  - [PASS] 必须上报YOLO与画面的矛盾：review.conflicts nonempty （实际 "['YOLO检测到火焰但画面中未见明显明火，存在视觉与检测结果的矛盾。']"）
- 结论: **FAIL**
