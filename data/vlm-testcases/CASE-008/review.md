# CASE-008 测试记录（02_run_cases.py 自动生成）

- 生成时间: 2026-09-06 21:14:06
- 模型: glm-4.6v-flash | 提示词: v3 | temperature 0.1 / max_tokens 2048
- 说明: 本文件反映最近一次运行的档位；各档完整证据见 runs/ 子目录，历史见 logs/
- 场景: 水源线索：林间带状明火+灰黑浓烟，火场位于湍急河流对岸（water_candidate案例）
- 图片: CASE-008-R1-F1=T08.jpg
- 人工核验依据: 2026-09-06人工核验：画面中部偏左至偏右林间横向带状明火（部分沿树干向上蔓延）+灰黑浓烟；下半部为宽阔湍急河流（青绿色，浪花岩石可见），火场在河对岸、火焰倒映水面；未见人员/道路/建筑/电力设备；画质清晰（色彩饱和度偏高，疑为合成/渲染图，仅作测试输入）

## Tier A-p3（A档：无YOLO（yolo_status=missing））

- 调用: HTTP 200 | 耗时 325.8s | 限流重试 4 次 | 格式修复重试 否
- tokens: prompt=1683 completion=1869 (reasoning=1449)
- 结构检查: 通过
- 禁止项扫描: 未发现
- 预期检查: 4/6 通过
  - [PASS] 明火可见：fire_observation.fire_presence eq flame_observed（实际 'flame_observed'）
  - [PASS] 烟量中等或浓：smoke_trend.smoke_density in ['medium', 'heavy']（实际 'heavy'）
  - [FAIL] 河流可见→water_candidate（禁止输出可取水判断）：object_clues.water.state eq water_candidate（实际 'not_observed'）
  - [FAIL] 水体证据非空（位置/形态）：object_clues.water.evidence nonempty （实际 ''）
  - [PASS] 画面无人员→not_observed：object_clues.people.state eq not_observed（实际 'not_observed'）
  - [PASS] 单轮图片→first_round_no_comparison：smoke_trend.temporal_trend eq first_round_no_comparison（实际 'first_round_no_comparison'）
- 结论: **FAIL**

## Tier B-p3（B档：空fixture（detections=[]，验证空结果不阻断观察））

- 调用: HTTP 200 | 耗时 34.7s | 限流重试 1 次 | 格式修复重试 否
- tokens: prompt=1705 completion=984 (reasoning=543)
- 结构检查: 通过
- 禁止项扫描: 未发现
- 预期检查: 5/7 通过
  - [PASS] 明火可见：fire_observation.fire_presence eq flame_observed（实际 'flame_observed'）
  - [PASS] 烟量中等或浓：smoke_trend.smoke_density in ['medium', 'heavy']（实际 'heavy'）
  - [FAIL] 河流可见→water_candidate（禁止输出可取水判断）：object_clues.water.state eq water_candidate（实际 'not_observed'）
  - [FAIL] 水体证据非空（位置/形态）：object_clues.water.evidence nonempty （实际 ''）
  - [PASS] 画面无人员→not_observed：object_clues.people.state eq not_observed（实际 'not_observed'）
  - [PASS] 单轮图片→first_round_no_comparison：smoke_trend.temporal_trend eq first_round_no_comparison（实际 'first_round_no_comparison'）
  - [PASS] 空fixture不得阻断观察：仍应报明火：fire_observation.fire_presence ne none_observed（实际 'flame_observed'）
- 结论: **FAIL**
