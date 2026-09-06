# VLM 交付交接清单（handoff-checklist）

- **交付人**: VLM负责队员
- **交付日期**: 2026-09-06（第1~3天完成）
- **接收人**: 队内开发同学
- **相关文档**: [prompt-v4.md](prompt-v4.md)（接入用提示词全文）| [evaluation-results.md](evaluation-results.md)（能力实测）| [api-call-example.md](api-call-example.md)（调用样例）

---

## 一、交付物清单

| 交付物 | 位置 | 说明 |
|---|---|---|
| 系统提示词交付版 v4 | docs/vlm-delivery/prompt-v4.md §二 | **直接复制使用**，含版本沿革与证据链 |
| 输出结构 vlm-analysis-v1 | prompt-v4.md §二（JSON骨架） | 所有字段+枚举，服务端按此校验 |
| 用户消息模板 | prompt-v4.md §三 + prompt-v1.md §三 | 含任务信息行、多图帧序列说明行 |
| 实测能力报告 | docs/vlm-delivery/evaluation-results.md | 12组案例、48次调用、通过率/耗时/token/限流、问题清单P01-P08 |
| API调用样例（去Key） | docs/vlm-delivery/api-call-example.md | 请求/响应结构 |
| 测试案例全集 | data/vlm-testcases/cases.json + CASE-001~012/ | 12组定义、人工预期(expected.json)、fixture(mock_yolo.json)、逐次调用证据(runs/) |
| 可复跑脚本 | scripts/ | vlm_api.py（调用+限流重试）、02_run_cases.py（全流程判卷）、01_smoke_test.py |
| .env.example | 根目录 | Key配置模板（真实Key只放.env，已被gitignore） |

## 二、开发者接入步骤（建议顺序）

1. **Key 配置**：标准API Key（非团队套餐Key）写入 `.env`（复制 .env.example）；**任何情况下 Key 不入库、不进日志、不写截图**。
2. **复制提示词**：prompt-v4.md §二 全文作为 system prompt；用户消息按 §三 模板拼装（多图轮次记得加帧序列说明行）。
3. **调用参数**：temperature 0.1 / max_tokens 2048 / 只接受纯JSON。
4. **必做的服务端防御**（对应报告 §7）：
   - 响应先剥离```围栏（取首`{`至末`}`）再解析；
   - 按 vlm-analysis-v1 校验字段与枚举；失败时把**具体错误字段**回传模型重试一次；
   - 限流退避重试 [15,40,90,150] 秒 + 调用间隔≥6秒；HTTP 200 空响应按失败重试；
   - 运行器注入身份字段（mode/source/yolo_status/model/analyzed_at），模型不输出这些。
5. **真实PWM-YOLO接入后**：A/B/C 档位测试已覆盖三种输入形态（missing/空/含框），fixture 格式见各案例 mock_yolo.json；接入后建议先用 CASE-003（假框矛盾上报）复测一次。

## 三、已知问题与红线（必读）

1. **P04 水源漏检 0/2**：VLM 的 water 字段不可单独作为水源依据，用 PWM-YOLO/人工兜底。
2. **P05 画质低报 0/2**：不要依赖 usable/problems 做可用性裁决。
3. **P06 晚高峰限流**：免费档 19:00–22:00 几乎不可用，错峰或退避；演示/比赛前预留重试与降级方案。
4. **红线（方案5.1）**：VLM 只输出视觉事实；FLP/面积/风速/无人机调度等一律禁止（实测48次0违规，服务端保留扫描兜底）；人工预期与模型实际输出分开存放，**不得人工改写模型输出**。
5. **图片版权**：测试图片来源未记录，**不得上传公开仓库**（公开交付包已剔除全部图片，仅保留案例定义与文字证据）。

## 四、待办移交

- [ ] 真实PWM-YOLO到位后联调（预计交付后~2天）
- [ ] P02 两处枚举规则（v4新增）随真实调用继续观察
- [ ] 若获得真实递减两帧图片，可补测 CASE-011 同款场景（现用替代组合，局限已在报告P08记录）
- [ ] 公开仓库推送前：队内审核 + 复查导出包无Key无图片
