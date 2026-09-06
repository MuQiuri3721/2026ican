"""API 边界与健壮性扫描：对全部端点打非法/边界输入，任何 5xx 都是缺陷（应 4xx）。

用法：python e2e/boundary_scan.py   （后端须已在 127.0.0.1:8000）
"""
import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"
RESULTS = []


def req(method, path, payload=None, timeout=60, raw=None):
    data = raw if raw is not None else (json.dumps(payload).encode() if payload is not None else None)
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:
        return f"EXC:{type(e).__name__}"


def record(case, path, method, status, expect=None):
    if expect is not None:
        bad = status != expect
    else:
        bad = not (isinstance(status, int) and 400 <= status < 500)
    RESULTS.append((case, method, path, status, bad))
    flag = "  <<< 异常" if bad else ""
    print(f"[{'!!' if bad else 'ok'}] {status} {method:6} {path[:70]}{flag}")


CREATED = []  # 扫描自建的任务（钳位/默认场景用例），终了统一清场


def cleanup_created():
    for tid in CREATED:
        req("POST", f"/api/tasks/{tid}/approval", {"action": "terminate", "reason": "boundary scan cleanup"})
    if CREATED:
        print(f"[清场] 终止扫描自建任务 {len(CREATED)} 个")


def main() -> int:
    # 记录扫描前最新任务，结束时终止扫描期间新增的非终态任务（钳位/默认场景用例会真实建任务）
    try:
        with urllib.request.urlopen(BASE + "/api/analyzes?limit=1&slim=1", timeout=30) as resp:
            items = json.loads(resp.read().decode())
            items = items if isinstance(items, list) else items.get("items", [])
            if items:
                CREATED.append(items[0]["analysis_id"])  # 哨兵：此后新建的都算扫描产物
    except Exception:  # noqa: BLE001
        pass

    print("=== 分析与研判边界 ===")
    # 钳位语义（FE-18 设计）：数值越界 → 钳到合理区间返回 200，非 422
    clamp_cases = [
        ("scenario 面积负数→钳位 200", {"scenario": {"fire_origin": {"x": 0, "y": 0}, "fire_area_m2": -5}}),
        ("scenario 增长率超大→钳位 200", {"scenario": {"fire_origin": {"x": 0, "y": 0}, "fire_area_m2": 500, "growth_rate": 99}}),
        ("scenario 坐标越界→钳位 200", {"scenario": {"fire_origin": {"x": 99999, "y": -99999}, "fire_area_m2": 500}}),
        ("空 body→默认演示场景 200", {}),
    ]
    for case, payload in clamp_cases:
        status = req("POST", "/api/analyze", payload)
        record(case, "/api/analyze", "POST", status, expect=200)
        try:
            with urllib.request.urlopen(BASE + "/api/analyzes?limit=1&slim=1", timeout=30) as resp:
                items = json.loads(resp.read().decode())
                items = items if isinstance(items, list) else items.get("items", [])
                if items and items[0]["analysis_id"] not in CREATED:
                    CREATED.append(items[0]["analysis_id"])
        except Exception:  # noqa: BLE001
            pass

    cases = [
        ("scenario 非对象", "POST", "/api/analyze", {"scenario": "big-fire"}),
        ("people_status 非法", "POST", "/api/analyze", {"people_status": "maybe"}),
        ("纬度越界", "POST", "/api/analyze", {"latitude": 999}),
        ("water_radius 超上限", "POST", "/api/analyze", {"water_search_radius_m": 999999}),
        ("constraints 非对象", "POST", "/api/analyze", {"constraints": [1, 2, 3]}),
    ]
    for case, method, path, payload in cases:
        record(case, path, method, req(method, path, payload), expect=422)

    print("=== 不存在的资源（应 404）===")
    for path, method, payload in [
        ("/api/analyze/analysis-notexist", "GET", None),
        ("/api/tasks/analysis-notexist/plan", "GET", None),
        ("/api/tasks/analysis-notexist/rounds", "POST", {"round": 1}),
        ("/api/tasks/analysis-notexist/approval", "POST", {"action": "approve"}),
        ("/api/tasks/analysis-notexist/report", "GET", None),
        ("/api/monitor/analysis-notexist", "POST", {"elapsed_minutes": 5}),
        ("/api/tasks/analysis-notexist/agent-messages", "GET", None),
    ]:
        record("不存在资源", path, method, req(method, path, payload))

    print("=== 轮次/监测边界（对真实执行中任务不好构造，用不存在任务验证入参校验顺序）===")
    for case, payload in [
        ("round=0", {"round": 0}),
        ("round 负数", {"round": -3}),
        ("elapsed=0", {"round": 1, "elapsed_minutes": 0}),
        ("elapsed 超上限", {"round": 1, "elapsed_minutes": 999}),
        ("extinguishing 负数", {"round": 1, "extinguishing_liters": -1}),
        ("extinguishing 超上限", {"round": 1, "extinguishing_liters": 99999}),
        ("flp 负数", {"round": 1, "fire_load_flp": -10}),
        ("wind 负数", {"round": 1, "wind_speed": -5}),
    ]:
        record(case, "/api/tasks/analysis-notexist/rounds", "POST", req("POST", "/api/tasks/analysis-notexist/rounds", payload))

    print("=== 审批动作边界 ===")
    for case, payload in [
        ("action 非法", {"action": "explode"}),
        ("action 空", {"action": ""}),
    ]:
        record(case, "/api/tasks/analysis-notexist/approval", "POST", req("POST", "/api/tasks/analysis-notexist/approval", payload))

    print("=== Skill 兼容通道 ===")
    record("未知 skill", "/api/skills/not-a-skill/run", "POST", req("POST", "/api/skills/not-a-skill/run", {}))
    # 兼容通道设计：确定性 skill 以默认入参执行并返回结果信封（200），非错误
    record("skill 空入参→默认执行", "/api/skills/fire_perception/run", "POST", req("POST", "/api/skills/fire_perception/run", {}), expect=200)

    print("=== 上传边界 ===")
    record("上传无文件", "/api/analyze/upload", "POST", req("POST", "/api/analyze/upload", {}, raw=b""))
    record("上传错误类型", "/api/analyze/upload", "POST", req("POST", "/api/analyze/upload", {}, raw=b"--x\nContent-Disposition: form-data; name=\"file\"; filename=\"a.exe\"\nContent-Type: application/x-msdownload\n\nMZ9090\n--x--\n"))

    print("=== 读端点冒烟（应 200）===")
    for path in [
        "/api/health", "/api/project-status", "/api/skills", "/api/tools",
        "/api/fleet", "/api/inventory", "/api/scenarios/random", "/api/llm-status",
        "/api/analyzes?limit=5&slim=1", "/api/terrain/grid",
        "/api/knowledge?query=" + urllib.parse.quote("疏散"),
        "/api/tts?text=%E7%96%8F%E6%95%A3%E6%B5%8B%E8%AF%95",
        "/api/environment?latitude=32.0725&longitude=118.8415",
    ]:
        status = req("GET", path, timeout=120 if ("terrain" in path or "environment" in path) else 40)
        ok = status == 200
        RESULTS.append(("读冒烟", "GET", path, status, not ok))
        print(f"[{'ok' if ok else '!!'}] {status} GET {path[:70]}{'  <<< 非 200' if not ok else ''}")

    print("=== SSE 快照 ===")
    record("SSE once=1", "/api/tasks/analysis-notexist/events/stream?once=1", "GET", req("GET", "/api/tasks/analysis-notexist/events/stream?once=1", timeout=15))

    cleanup_created()
    server_errors = [r for r in RESULTS if r[4]]
    print(f"\n=== 扫描结论：{len(RESULTS)} 项，{len(server_errors)} 项异常 ===")
    for case, method, path, status, _ in server_errors:
        print(f"  !! {status} {method} {path} ({case})")
    return 1 if server_errors else 0


if __name__ == "__main__":
    sys.exit(main())
