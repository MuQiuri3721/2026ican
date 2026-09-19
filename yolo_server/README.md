# local-yolo-service（E-1 替代方案）

D-Fire 训练的 YOLO11n 检测服务，等 PWM-Net 原始权重期间充当**真实检测源**——
系统从此分析的不是预置 fixture，而是真模型对真实图片的检测框。

## 训练（一次性）

```bash
# 1. 数据集（D-Fire 官方镜像，CC BY 4.0；已 gitignore 不入库）
#    data/dfire/train.tar ← HF hanvithSai/gavin-dfire-raw（21,527 图 + YOLO 标注）
# 2. 整理 + 训练（RTX 5070 上 40 epochs 约 1.5-2 小时）
python scripts/yolo/train_dfire.py --epochs 40
# 产物 yolo_server/best.pt（mAP 与类别表见训练输出）
```

## 启动服务

```bash
pip install ultralytics fastapi uvicorn   # torch 需 CUDA 版（cu128）
python yolo_server/server.py --port 9000
# 健康检查: curl http://127.0.0.1:9000/health
```

## 平台接入

`.env` 追加一行后重启后端：

```
FIRE_YOLO_ENDPOINT=http://127.0.0.1:9000/detect
```

上传图片后研判链路走真实检测（`mode=real`），前端模型状态行显示：
`YOLO real · yolo11n-dfire-v1 · local-yolo-service`；服务停掉自动回落
fixture 并标注 `yolo_endpoint_unavailable`（演示不中断）。

## 协议

与 `docs/YOLO队员交付说明.md` §2 完全一致：POST 图片字节 →
`{detections:[{class_name, confidence, box:[x1,y1,x2,y2]}], image_width,
image_height, source, model}`。PWM-Net 原始权重到位后，同一端点换服务即可，
平台零改动。
