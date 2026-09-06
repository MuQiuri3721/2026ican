# API 调用样例（已去除密钥 / KEY REMOVED）

> 本文档供开发者实现 `VLMClient` 时参考。所有请求样例已去除真实 Key 和完整 Base64 图片数据。样例均来自 2026-09-06 真实调用（见 `logs/smoke_test_20260906_193159.json`）。

## 一、基本信息

| 项 | 值 |
|---|---|
| 接口地址 | `https://open.bigmodel.cn/api/paas/v4/chat/completions` |
| 请求方法 | POST |
| 鉴权方式 | 请求头 `Authorization: Bearer <标准API Key>` |
| 模型名 | `glm-4.6v-flash` |
| 图片传入方式 | `image_url.url` 支持 **公网URL** 或 **Base64数据流**（`data:image/jpeg;base64,...`）。本项目实测使用 Base64，不依赖图床 |

## 二、请求头（Key 通过环境变量注入，禁止硬编码）

```http
Authorization: Bearer ${ZHIPU_API_KEY}
Content-Type: application/json
```

## 三、单图请求样例（Base64方式）

```json
{
  "model": "glm-4.6v-flash",
  "messages": [
    {
      "role": "user",
      "content": [
        {
          "type": "image_url",
          "image_url": { "url": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQ...（完整Base64，实测252KB图片约33万字符）" }
        },
        {
          "type": "text",
          "text": "请用中文简短描述这张（这些）图片：画面里是否有火焰、烟雾、人员、道路、建筑、电力设备或水面？只描述你能看到的内容。"
        }
      ]
    }
  ],
  "temperature": 0.1,
  "max_tokens": 2048
}
```

## 四、多图请求样例（3张，按时间顺序放同一个content数组）

```json
{
  "model": "glm-4.6v-flash",
  "messages": [
    {
      "role": "user",
      "content": [
        { "type": "image_url", "image_url": { "url": "data:image/jpeg;base64,...(第1帧)" } },
        { "type": "image_url", "image_url": { "url": "data:image/jpeg;base64,...(第2帧)" } },
        { "type": "image_url", "image_url": { "url": "data:image/jpeg;base64,...(第3帧)" } },
        { "type": "text", "text": "（同上的提问文字）" }
      ]
    }
  ],
  "temperature": 0.1,
  "max_tokens": 2048
}
```

## 五、真实响应样例（多图调用，2026-09-06 19:31 实测）

```json
{
  "choices": [
    {
      "message": {
        "content": "\n这些图片展示了森林火灾场景，画面中有火焰（红色、橙色）、烟雾（白色和灰色），周围有树木，地面有枯黄植被，没有明显的人员、道路、建筑、电力设备或水面。"
      }
    }
  ],
  "model": "glm-4.6v-flash",
  "usage": {
    "prompt_tokens": 4047,
    "completion_tokens": 258,
    "completion_tokens_details": { "reasoning_tokens": 210 },
    "total_tokens": 4305
  }
}
```

> 注意：glm-4.6v-flash 是带推理能力的模型，usage 中会出现 reasoning_tokens；文本输出可能以 `\n` 开头，解析时建议先 strip。

## 六、实测性能与限流情况（开发者必须知道）

| 指标 | 实测值（7次调用，2026-09-06 19:29—19:32） |
|---|---|
| 成功率 | 7/7 |
| 平均耗时 | 约 19.7 秒 |
| 最短/最长 | 13.1 秒 / 31.8 秒 |
| 单图 prompt_tokens | 约 908（252KB 图片） |
| 3图 prompt_tokens | 约 4047（485KB 共3张） |
| 限流(429) | 高峰期会出现；实测对策：调用间隔 6 秒 + 遇 429/5xx 按 12/25/50 秒退避自动重试，重试后均成功 |
| 建议 | 后端 VLMClient 内置指数退避重试（至少3次）；不要并发轰炸免费模型 |

## 七、错误码速查（实测/官方口径）

| HTTP | 含义 | 处理 |
|---|---|---|
| 401 | Key 无效/未认证 | 检查环境变量中的 Key 是否完整（两段式 `id.secret`） |
| 429 | 限流/访问量过大 | 退避重试（见上表） |
| 400 | 请求格式错误 | 检查 content 数组结构、Base64 前缀 `data:image/jpeg;base64,` |
