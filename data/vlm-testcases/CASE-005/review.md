# CASE-005 测试记录（02_run_cases.py 自动生成）

- 生成时间: 2026-09-06 20:59:53
- 模型: glm-4.6v-flash | 提示词: v3 | temperature 0.1 / max_tokens 2048
- 说明: 本文件反映最近一次运行的档位；各档完整证据见 runs/ 子目录，历史见 logs/
- 场景: 火场有人员：7~8名橙红色救援服人员在山坡接近火线扑救，火线沿山坡蔓延
- 图片: CASE-005-R1-F1=T05.jpg
- 人工核验依据: 2026-09-06人工核验：画面下方7-8名橙红救援服人员（戴盔、持工具）接近火线；树干间与右上角有明火；天空灰白烟浓；无消防车/道路/建筑/水面

## Tier A-p3（A档：无YOLO（yolo_status=missing））

- 调用: HTTP 200 | 耗时 21.8s | 限流重试 0 次 | 格式修复重试 否
- tokens: prompt=1635 completion=2021 (reasoning=1583)
- 结构检查: 通过
- 禁止项扫描: 未发现
- 预期检查: 3/3 通过
  - [PASS] 人员可见→observed：object_clues.people.state eq observed（实际 'observed'）
  - [PASS] 人员证据非空（人数/位置/服装）：object_clues.people.evidence nonempty （实际 '图片中可见多名穿着橙色消防服的人员'）
  - [PASS] 明火可见：fire_observation.fire_presence eq flame_observed（实际 'flame_observed'）
- 结论: **PASS**

## Tier C-p3（C档：fixture含人工框（mode=fixture, source=manual_fixture））

- 调用: HTTP 200 | 耗时 15.2s | 限流重试 0 次 | 格式修复重试 否
- tokens: prompt=1735 completion=1115 (reasoning=711)
- 结构检查: 通过
- 禁止项扫描: 未发现
- 预期检查: 3/3 通过
  - [PASS] 人员可见→observed：object_clues.people.state eq observed（实际 'observed'）
  - [PASS] 人员证据非空（人数/位置/服装）：object_clues.people.evidence nonempty （实际 '画面中可见多名穿着橙色消防服的人员'）
  - [PASS] 明火可见：fire_observation.fire_presence eq flame_observed（实际 'flame_observed'）
- 结论: **PASS**
