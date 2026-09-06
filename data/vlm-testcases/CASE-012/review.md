# CASE-012 测试记录（02_run_cases.py 自动生成）

- 生成时间: 2026-09-06 21:43:31
- 模型: glm-4.6v-flash | 提示词: v4 | temperature 0.1 / max_tokens 2048
- 说明: 本文件反映最近一次运行的档位；各档完整证据见 runs/ 子目录，历史见 logs/
- 场景: 帧间基本稳定对比：两帧均为左侧弧形火带（约1/3画面宽）+大片过火焦黑+浓烟；中部偏右有疑似扑火人员（远距航拍橙红点串，不确定，仅记录不设硬检查）
- 图片: CASE-012-R1-F1=T12A.jpg，CASE-012-R1-F2=T12B.jpg
- 人工核验依据: 2026-09-06人工核验：T12A左侧弧形橙红火带（约1/3画面宽）+灰白至灰黑浓烟+中上部/右侧焦黑过火痕；T12B左侧及左下多处弧形火线+零星小火点+浓厚灰白烟+中部偏右焦黑；两帧中部偏右均有疑似橙红服装人员（远距航拍无法确认，帧1旁疑似白色水带）；人工判定两帧火线位置与规模相近（基本稳定）

## Tier A-p4（A档：无YOLO（yolo_status=missing））

- 调用: HTTP 200 | 耗时 75.7s | 限流重试 2 次 | 格式修复重试 否
- tokens: prompt=5105 completion=1480 (reasoning=1045)
- 结构检查: 通过
- 禁止项扫描: 未发现
- 预期检查: 5/5 通过
  - [PASS] 明火可见：fire_observation.fire_presence eq flame_observed（实际 'flame_observed'）
  - [PASS] 烟量中等或浓：smoke_trend.smoke_density in ['medium', 'heavy']（实际 'heavy'）
  - [PASS] 基本稳定或如实看不出（人工判定两帧相近）：smoke_trend.temporal_trend in ['stable', 'unclear']（实际 'unclear'）
  - [PASS] 航拍林地无建筑→not_observed（防幻觉）：object_clues.building.state eq not_observed（实际 'not_observed'）
  - [PASS] 无水面→not_observed（防幻觉）：object_clues.water.state eq not_observed（实际 'not_observed'）
- 结论: **PASS**
