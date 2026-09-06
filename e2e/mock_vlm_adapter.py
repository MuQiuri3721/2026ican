"""本地 mock VLM 适配器（一级来源 FIRE_VLM_ENDPOINT 的无 Key 验证工具）。

按交付契约 vlm-analysis-v1（prompt-v4 §二嵌套分组）返回固定载荷，回显请求中的
task_id/round_index，供端到端验证"上传→VLM→契约守卫→展平→落库→前端 vlm-note"全链，
无需真实 Key。用法：

    python e2e/mock_vlm_adapter.py [port=8765]
    # 后端以 FIRE_VLM_ENDPOINT=http://127.0.0.1:8765/vlm 启动即生效
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            body = {}
        observation = body.get("observation") or {}
        task_id = observation.get("task_id") or "mock-task"
        round_index = observation.get("round_index") or 1
        payload = {
            "schema_version": "vlm-analysis-v1",
            "task_id": task_id,
            "round_index": round_index,
            "image_ids": ["F1"],
            "prompt_version": "v4",
            "image_quality": {"usable": True, "quality_level": "good", "problems": ["none"], "missing_inputs": ["PWM-YOLO结果"]},
            "fire_observation": {"fire_presence": "flame_observed", "affected_layer": "surface",
                                 "canopy_involvement": "not_observed", "visual_scale": "medium"},
            "smoke_trend": {"smoke_density": "heavy", "image_plane_drift": "uncertain",
                            "temporal_trend": "first_round_no_comparison"},
            "object_clues": {
                "people": {"state": "not_observed", "evidence": ""},
                "road": {"state": "not_observed", "evidence": ""},
                "building": {"state": "not_observed", "evidence": ""},
                "power_equipment": {"state": "not_observed", "evidence": ""},
                "water": {"state": "water_candidate", "evidence": ""},
                "obstacle": {"state": "not_observed", "evidence": ""},
            },
            "review": {"conflicts": [], "manual_review_required": False,
                       "human_summary": "画面中可见明显火焰与浓烟，地表火带蔓延，未观察到人员与建筑物。"},
        }
        data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # 静默访问日志
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print(f"mock vlm adapter on http://127.0.0.1:{port}/vlm")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
