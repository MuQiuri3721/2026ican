# CASE-006 测试记录（02_run_cases.py 自动生成）

- 生成时间: 2026-09-06 21:00:12
- 模型: glm-4.6v-flash | 提示词: v3 | temperature 0.1 / max_tokens 2048
- 说明: 本文件反映最近一次运行的档位；各档完整证据见 runs/ 子目录，历史见 logs/
- 场景: 无人员火场：左侧明火+中等偏浓烟，画面仔细检查无人，分辨率偏低
- 图片: CASE-006-R1-F1=T06.jpg
- 人工核验依据: 2026-09-06人工核验：左侧及中下部明显明火（约占左半），烟灰白+深灰中等偏浓；仔细检查无人员；无道路/建筑/电力/水面；分辨率偏低有压缩痕迹

## Tier A-p3（A档：无YOLO（yolo_status=missing））

- 调用: HTTP 200 | 耗时 19.1s | 限流重试 0 次 | 格式修复重试 否
- tokens: prompt=1443 completion=1169 (reasoning=743)
- 结构检查: 通过
- 禁止项扫描: 未发现
- 预期检查: 2/2 通过
  - [PASS] 明火可见：fire_observation.fire_presence eq flame_observed（实际 'flame_observed'）
  - [PASS] 未见人员→not_observed（禁止absent）：object_clues.people.state eq not_observed（实际 'not_observed'）
- 结论: **PASS**
