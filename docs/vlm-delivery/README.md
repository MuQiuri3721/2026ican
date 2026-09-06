# 火巡智策 · VLM 视觉分析模块交付包

> 入库说明（2026ican 主仓库接收时添加）：本目录及 `data/vlm-testcases/`、`scripts/` 为 VLM 负责队员
> 2026-09-06 微信交付包（vlm-handoff-github）原样入库；交付包根 README 移入本目录，`.env.example`
> 与 `.gitignore` 未复制（主仓库根已有同 role 文件）。文中相对路径以主仓库根为基准仍成立。

森林火灾无人机侦察项目的视觉语言模型（VLM）能力验证与交付材料。
由 VLM 负责队员完成（2026-09-06），交付给队内开发同学接入。

## 一句话结论

模型 **glm-4.6v-flash**（智谱标准API免费档）+ 提示词 **v4**：内容判断正确率 **90.6%**（77/85 项）、红线禁止项 **48 次调用 0 违规**、纯模型响应中位 **19 秒**；两个真实短板（水源漏检、画质低报）与限流对策均已写入报告。

## 目录结构

```
docs/vlm-delivery/           交付文档（按此顺序读）
  ├── handoff-checklist.md   ① 交接清单：交付物、接入步骤、红线、待办
  ├── prompt-v4.md           ② 接入用系统提示词全文（最终交付版）
  ├── evaluation-results.md  ③ 实测统计报告：通过率/耗时/token/限流/问题清单/接入建议
  ├── model-selection.md     ④ 选型说明：为什么选它、限制、升级路径
  ├── api-call-example.md    ⑤ API 调用样例（已去Key）
  ├── prompt-v1.md           提示词 v1（冻结版，版本沿革起点）
  └── prompt-v3.md           提示词 v3（已被 v4 取代，保留作证据）
data/vlm-testcases/          12 组测试案例
  ├── cases.json             案例总表：场景、档位、人工预期检查项、状态
  └── CASE-001~012/          每组：metadata / expected(人工预期) / mock_yolo(fixture)
                              / review(判卷记录) / runs/<档位>/(逐次调用证据)
scripts/                     可复跑脚本
  ├── vlm_api.py             API 封装：Key读取、Base64、限流退避重试
  ├── 01_smoke_test.py       冒烟测试
  ├── 02_run_cases.py        案例运行器：调用+四层判卷+证据落盘
  └── 00_normalize_images.py 图片规范化（本地用）
.env.example                 Key 配置模板（真实 Key 只放 .env，绝不入库）
```

## 快速开始（开发者）

1. `cp .env.example .env`，填入**标准API Key**（非团队套餐Key）
2. 读 [docs/vlm-delivery/handoff-checklist.md](docs/vlm-delivery/handoff-checklist.md) §二 按步骤接入
3. 系统提示词直接复制 [docs/vlm-delivery/prompt-v4.md](docs/vlm-delivery/prompt-v4.md) §二
4. 复跑测试：`python scripts/02_run_cases.py --prompt-version v4`（需自备测试图片放 `data/vlm-testcases/_raw_images/`，见下）

## 安全与合规说明

- **本包不含任何 API Key**：请求证据中的 Key 均已脱敏（仅保留前4字符+****）
- **本包不含任何测试图片**：图片来源未记录、版权状态不明，仅限队内使用，不上传公开仓库；图片哈希与大小记录在各案例 metadata.json 的 frames 字段，可校验图片一致性
- 模型输出证据（raw_response.json）一字未改，人工预期（expected.json）与模型实际输出分开存放
- 测试结论诚实呈现：失败案例、能力短板、限流失败均如实记录（见 evaluation-results.md §6 问题清单）
