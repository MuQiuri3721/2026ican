"""本地 mock PWM-YOLO 适配器（一级检测来源 FIRE_YOLO_ENDPOINT 的无服务验证工具）。

按 docs/api-contract.md §9 协议响应：POST 原始图片字节 → JSON（必含 detections 数组，
可选字段缺省时由平台规则工具从检测框推算）。供端到端验证"上传→真实检测→面积/等级
推算→前端来源徽标"全链，无需真实 PWM-YOLO 服务。

用法：
    python e2e/mock_yolo_adapter.py [port=8766] [--mode real|empty|garbage]
      real    固定返回一组合理的 fire/smoke 检测框（默认）
      empty   返回空 detections（验证"确认无火"路径）
      garbage 返回非 JSON（验证回退/strict_real 错误路径）
后端以 FIRE_YOLO_ENDPOINT=http://127.0.0.1:<port>/detect 启动即生效。
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

MODE = "real"

DETECTIONS = [
    {"class_name": "fire", "confidence": 0.93, "box": [820, 410, 1130, 760]},
    {"class_name": "fire", "confidence": 0.88, "box": [980, 520, 1240, 700]},
    {"class_name": "smoke", "confidence": 0.89, "box": [650, 180, 1420, 820]},
]


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)  # 消费图片字节
        if MODE == "garbage":
            data = b"<html>not-json</html>"
            status = 200
        elif MODE == "empty":
            data = json.dumps({"detections": [], "image_width": 1920, "image_height": 1080}).encode()
            status = 200
        else:
            data = json.dumps({"detections": DETECTIONS, "image_width": 1920, "image_height": 1080}).encode()
            status = 200
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # 静默访问日志
        pass


if __name__ == "__main__":
    port = 8766
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        port = int(args[0])
    if "--empty" in sys.argv:
        MODE = "empty"
    if "--garbage" in sys.argv:
        MODE = "garbage"
    print(f"mock yolo adapter on http://127.0.0.1:{port}/detect (mode={MODE})")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
