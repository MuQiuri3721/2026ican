# 火巡智策 YOLO 队员交付说明

> PWM-YOLO 检测服务交付与联调指引
> 登记日期:2026-09-07 · 对应追踪清单 E-1(YOLO/PWM-YOLO 独立检测服务交付)· 对接人:听日
> 平台侧接收面**已就绪并全链验证**(mock 实测通过),按本说明交付即可即插即用。

## 1 你要交付什么

一个**独立运行的 HTTP 检测服务**:接收航拍图片字节,返回火焰/烟雾检测框 JSON。
不需要读平台代码、不需要数据库;权重 + 推理脚本 + 启动方式就是全部。

| 交付物 | 要求 |
|---|---|
| 模型权重与推理代码 | 自包含目录,`README` 写明 Python 版本与依赖安装命令 |
| 启动方式 | 一条命令起 HTTP 服务(如 `python server.py --port 9000`),写明实际端口 |
| 接口契约 | 完全按 §2 实现(平台侧超时只有 **5 秒**) |
| 冒烟自测记录 | 用 §4 的 curl 命令对 3 张不同分辨率图片各跑一次,保存响应 JSON |

## 2 接口契约(docs/api-contract.md §9,冻结)

- **请求**:`POST <你的端点>`,body 为**原始图片字节**,`Content-Type: application/octet-stream`。平台只发 **JPG/PNG**(视频由平台侧抽帧后再发,你不需要处理视频)。
- **响应**:JSON object,**必须**包含 `detections` 数组,缺它整包视为协议错误:

```json
{
  "detections": [
    {"class_name": "fire",  "confidence": 0.93, "box": [820, 410, 1130, 760]},
    {"class_name": "smoke", "confidence": 0.89, "box": [650, 180, 1420, 820]}
  ],
  "image_width": 1920, "image_height": 1080
}
```

- `class_name ∈ {fire, smoke, building, obstacle, ...}`;`fire/smoke` 参与面积统计。
- `box = [x1, y1, x2, y2]` **像素坐标**(同图的 image_width/height 系);confidence 0~1。
- `detections` 之后的字段全部可选——面积/增长率/置信度等缺省时由平台规则工具从检测框推算,不要自己算 FLP。
- 平台调用时带 5 秒超时;无检测目标时返回 `"detections": []`(不是错误)。

## 3 平台侧行为(你需要知道的)

| 场景 | 表现 |
|---|---|
| 未配置你的端点 | 平台用 fixture(`mode=demo`,界面如实标注"待接入") |
| 调用成功 | 结果带 `mode="real"`、`source="pwm-yolo-adapter"`,前端与报告如实展示 |
| 调用失败/响应非法 | 界面回落 fixture 并标注 `yolo_endpoint_unavailable`;`environment_mode=real` 时改为显式报错不掩盖 |

**红线**:不得在响应里输出 FLP、面积结论、调度建议——你只负责"看到了什么、在哪、多确信"。

## 4 交付前自测(两步)

1. **测你自己的服务**(图片字节直传):

```bash
curl -s -X POST http://127.0.0.1:9000/detect \
     -H "Content-Type: application/octet-stream" \
     --data-binary @你的测试图片.jpg
```

2. **与平台对拍**:仓库里带了一个行为同 §2 的 mock(`e2e/mock_yolo_adapter.py`)。启动平台时把 `FIRE_YOLO_ENDPOINT` 指向 mock 跑通一次,再指向你的服务跑同样流程,对比 `mode/source/detections` 即完成字段对齐:

```bash
python e2e/mock_yolo_adapter.py 8766            # --empty 测无目标;--garbage 测平台回退
cd backend && FIRE_YOLO_ENDPOINT=http://127.0.0.1:8766/detect python -m uvicorn app.main:app --port 8000
```

## 5 平台侧验收标准(E-1 关闭条件)

| 项 | 通过标准 |
|---|---|
| 契约 | 响应必含 detections 数组;class_name/box/confidence 语义正确 |
| 稳定 | 连续 10 次调用无失败,单次响应 < 5 秒(平台超时) |
| 分辨率 | 至少 2 种分辨率图片(如 1920×1080 与 640×480)结果坐标均正确 |
| 端到端 | 平台配置端点后上传同批图片,研判面板显示 `pwm-yolo-adapter` 来源且面积随检测框变化 |
| 回退 | 服务手动停掉后,平台自动落回 fixture 并标注(演示不中断) |

## 6 安全与渠道

- 服务部署在本机/内网,**不需要任何 API Key**。
- 权重与训练数据**不上传公开仓库**;交付走队内渠道,平台侧只在 `.env` 配一个 `FIRE_YOLO_ENDPOINT` 地址。
