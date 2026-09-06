# CASE-004 测试记录（02_run_cases.py 自动生成）

- 生成时间: 2026-09-06 21:32:38
- 模型: glm-4.6v-flash | 提示词: v3 | temperature 0.1 / max_tokens 2048
- 说明: 本文件反映最近一次运行的档位；各档完整证据见 runs/ 子目录，历史见 logs/
- 场景: 劣质图：夜间过暗+前景树枝遮挡+模糊，但火光带仍可辨认
- 图片: CASE-004-R1-F1=T04.jpg
- 人工核验依据: 2026-09-06人工核验：夜间图整体近黑、前景树枝剪影遮挡、火光边缘模糊；中下部橙红火光带+被映红的烟清晰可辨；无人员/道路/建筑/水面（右上角疑似细电线不确定）

## Tier A-p3（A档：无YOLO（yolo_status=missing））

- 调用: HTTP 200 | 耗时 314.1s | 限流重试 4 次 | 格式修复重试 否
- tokens: prompt=1657 completion=1208 (reasoning=807)
- 结构检查: 通过
- 禁止项扫描: 未发现
- 预期检查: 2/3 通过
  - [PASS] 劣质图：usable=false 或 missing_inputs非空：SPECIAL usable_or_missing （usable=True, missing_inputs=['yolo_result']）
  - [FAIL] 质量问题须如实列出（过暗/模糊/遮挡/低分辨率至少一项）：image_quality.problems contains_any ['too_dark', 'blurry', 'obstruction', 'low_resolution']（实际 ['none']，命中 []）
  - [PASS] 火光仍可辨认→flame_observed：fire_observation.fire_presence eq flame_observed（实际 'flame_observed'）
- 结论: **FAIL**
