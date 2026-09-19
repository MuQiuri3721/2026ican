"""本地 YOLO 检测服务（E-1 替代方案：D-Fire 训练的 YOLO11n，等 PWM-Net 原始权重期间使用）。

协议（docs/YOLO队员交付说明.md §2，与平台 FIRE_YOLO_ENDPOINT 对齐）：
- POST /detect：请求体 = 图片字节（Content-Type: application/octet-stream）
- 响应 = {"detections": [{"class_name", "confidence", "box": [x1,y1,x2,y2] 像素坐标}],
          "image_width", "image_height", "source", "model"}
- 无目标返回 "detections": []（不是错误）；只报"看到什么在哪多确信"，禁止输出 FLP/面积/调度。

用法：
    python yolo_server/server.py --port 9000 --weights yolo_server/best.pt
平台接入（.env 或环境变量）：
    FIRE_YOLO_ENDPOINT=http://127.0.0.1:9000/detect
"""
from __future__ import annotations

import argparse
import io
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ultralytics import YOLO

MODEL_NAME = "yolo11n-dfire-v1"
SOURCE = "local-yolo-service"
# D-Fire 类别序（训练 data.yaml 生成时锁定）：0=fire 1=smoke
CLASS_NAMES = {0: "fire", 1: "smoke"}

app = FastAPI(title="local-yolo-service")
_model: YOLO | None = None


def load_model(weights: Path) -> None:
    global _model
    _model = YOLO(str(weights))


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL_NAME, "source": SOURCE,
            "loaded": _model is not None}


@app.post("/detect")
async def detect(request: Request):
    started = time.time()
    payload = await request.body()
    if not payload:
        return JSONResponse(status_code=400, content={"error": "empty body"})
    try:
        import cv2
        import numpy as np
        image = cv2.imdecode(np.frombuffer(payload, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return JSONResponse(status_code=415, content={"error": "unreadable image"})
        height, width = image.shape[:2]
    except ImportError:
        # cv2 缺失时用 PIL 兜底解码，推理走 numpy 数组
        from PIL import Image
        pil = Image.open(io.BytesIO(payload)).convert("RGB")
        width, height = pil.size
        image = pil

    results = _model.predict(image, verbose=False, conf=0.25)
    detections = []
    for result in results:
        names = result.names
        for box in result.boxes:
            class_id = int(box.cls.item())
            x1, y1, x2, y2 = (float(v) for v in box.xyxy[0].tolist())
            detections.append({
                "class_name": CLASS_NAMES.get(class_id, names.get(class_id, f"class_{class_id}")),
                "confidence": round(float(box.conf.item()), 4),
                "box": [round(x1), round(y1), round(x2), round(y2)],
            })

    return {
        "detections": detections,
        "image_width": width,
        "image_height": height,
        "source": SOURCE,
        "model": MODEL_NAME,
        "inference_ms": round((time.time() - started) * 1000, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="local YOLO detection service")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--weights", default=str(Path(__file__).parent / "best.pt"))
    args = parser.parse_args()

    weights = Path(args.weights)
    if not weights.exists():
        raise SystemExit(f"权重不存在: {weights}（先运行 scripts/yolo/train_dfire.py 训练导出）")
    load_model(weights)
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
