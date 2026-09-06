# CASE-011 测试记录（02_run_cases.py 自动生成）

- 生成时间: 2026-09-06 21:42:15
- 模型: glm-4.6v-flash | 提示词: v4 | temperature 0.1 / max_tokens 2048
- 说明: 本文件反映最近一次运行的档位；各档完整证据见 runs/ 子目录，历史见 logs/
- 场景: 替代递减组（原T11a/b缺图）：帧1浓烟弥漫无明火(T02)→帧2无火无烟健康林(T03)，模拟火情熄灭烟消散。注意：两帧为替代组合、非真实同场景连续帧（诚实标注）
- 图片: CASE-011-R1-F1=T02.jpg，CASE-011-R1-F2=T03.jpg
- 人工核验依据: 2026-09-06人工核验：T02仅灰白浓烟、无任何火苗；T03茂密阔叶林、无火无烟；按输入设定（同火场前后帧）人工判定帧2较帧1火情明显减弱（烟消散）；两帧实为缺图替代组合、非真实连续帧，此局限已如实记录

## Tier A-p4（A档：无YOLO（yolo_status=missing））

- 调用: HTTP 200 | 耗时 43.9s | 限流重试 1 次 | 格式修复重试 否
- tokens: prompt=4012 completion=1915 (reasoning=1487)
- 结构检查: 通过
- 禁止项扫描: 未发现
- 预期检查: 2/3 通过
  - [PASS] 两帧均无明火，禁止报flame_observed（防幻觉核心）：fire_observation.fire_presence in ['smoke_only', 'none_observed', 'uncertain']（实际 'smoke_only'）
  - [FAIL] 递减或如实看不出（人工判定帧2明显减弱，禁止答intensifying）：smoke_trend.temporal_trend in ['weakening', 'unclear']（实际 'first_round_no_comparison'）
  - [PASS] 画面无人员→not_observed：object_clues.people.state eq not_observed（实际 'not_observed'）
- 结论: **FAIL**
