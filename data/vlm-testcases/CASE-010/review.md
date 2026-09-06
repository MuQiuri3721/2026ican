# CASE-010 测试记录（02_run_cases.py 自动生成）

- 生成时间: 2026-09-06 21:49:59
- 模型: glm-4.6v-flash | 提示词: v4 | temperature 0.1 / max_tokens 2048
- 说明: 本文件反映最近一次运行的档位；各档完整证据见 runs/ 子目录，历史见 logs/
- 场景: 帧间递增对比：帧1山坡林缘明火+灰白浓烟(T10A)→帧2山坡上方大面积条带状明火+浓黑烟(T10B)。视频截图，含台标/字幕叠加
- 图片: CASE-010-R1-F1=T10A.jpg，CASE-010-R1-F2=T10B.jpg
- 人工核验依据: 2026-09-06人工核验：T10A右下侧林缘明火沿山坡分布+大面积灰白烟；T10B中部偏右山坡上方大面积条带状明火（规模更大）+右侧浓黑烟；两帧均无人员/道路/建筑/电力设备/水面；人工判定帧2火势与烟量强于帧1（递增）；两帧均为带台标/字幕的视频截图

## Tier A-p4（A档：无YOLO（yolo_status=missing））

- 调用: HTTP 200 | 耗时 48.6s | 限流重试 1 次 | 格式修复重试 否
- tokens: prompt=4589 completion=2048 (reasoning=2046)
- 错误: 返回内容为空
- 结构检查: 未通过
  - [问题] JSON无法解析: None
- 禁止项扫描: 未发现
- 预期检查: 0/4 通过
  - [FAIL] 明火可见：fire_observation.fire_presence eq flame_observed（模型输出未解析）
  - [FAIL] 烟量中等或浓：smoke_trend.smoke_density in ['medium', 'heavy']（模型输出未解析）
  - [FAIL] 帧间递增或如实看不出（人工判定帧2更强，禁止答weakening）：smoke_trend.temporal_trend in ['intensifying', 'unclear']（模型输出未解析）
  - [FAIL] 画面无人员→not_observed：object_clues.people.state eq not_observed（模型输出未解析）
- 结论: **FAILED_API**
