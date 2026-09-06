# -*- coding: utf-8 -*-
"""
01_smoke_test.py — 冒烟测试（方案第2.3节 / 第8.1节第1天上午任务）

目的：验证 glm-4.6v-flash 通过智谱标准API能稳定看图。
做什么：
    1) 从 .env 读取 ZHIPU_API_KEY（绝不写死在代码里，绝不出现在日志里）
    2) 用第1张图做一次单图调用
    3) 如果给了2张以上，做一次多图调用
    4) 用第1张图连续调用5次，记录每次是否成功、耗时
    5) 全部结果保存到 logs/smoke_test_时间.json（自动排除Key）

用法（在 vlm-prep 目录下运行）：
    python scripts/01_smoke_test.py 图片1.jpg
    python scripts/01_smoke_test.py 图片1.jpg 图片2.jpg 图片3.jpg
"""
import base64
import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding="utf-8")

API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
MODEL = "glm-4.6v-flash"

QUESTION = ("请用中文简短描述这张（这些）图片：画面里是否有火焰、烟雾、人员、"
            "道路、建筑、电力设备或水面？只描述你能看到的内容。")


def load_api_key():
    """从项目根目录的 .env 读取 Key，并做基础检查。"""
    env_path = ROOT / ".env"
    if not env_path.exists():
        sys.exit("[错误] 找不到 .env 文件: %s" % env_path)
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("ZHIPU_API_KEY="):
            key = line.split("=", 1)[1].strip().strip('"').strip("'")
            if not key or not key.isascii() or key == "your_api_key_here":
                sys.exit("[错误] .env 里的 Key 还没换成真实的。请用记事本打开 vlm-prep\\.env，"
                         "把「在这里粘贴你的Key」替换成你的智谱标准API Key，保存后重新运行。")
            return key
    sys.exit("[错误] .env 里没有 ZHIPU_API_KEY= 这一行，文件可能被改坏了，请告诉我。")


def file_sha256(path):
    """计算文件哈希（方案6.1要求：图片要留哈希记录）。"""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def image_to_data_url(path):
    """把本地图片读成 base64 数据流（模型直接读图，不依赖图片外链）。"""
    p = Path(path)
    if not p.exists():
        sys.exit("[错误] 图片不存在: %s" % p)
    suffix = p.suffix.lower().lstrip(".")
    if suffix in ("jpg", "jpeg"):
        mime = "jpeg"
    elif suffix == "png":
        mime = "png"
    else:
        sys.exit("[错误] 只支持 jpg/png 图片，收到: %s" % p.name)
    size_mb = p.stat().st_size / 1024 / 1024
    if size_mb > 4.5:
        sys.exit("[错误] 图片 %s 太大(%.1fMB)，请先压缩到4MB以内" % (p.name, size_mb))
    b64 = base64.b64encode(p.read_bytes()).decode()
    return "data:image/%s;base64,%s" % (mime, b64)


# 免费模型高峰期会限流(429)，这里配置自动等待重试：每次失败后等更久再试
RETRY_BACKOFF_SECONDS = [12, 25, 50]   # 第1/2/3次重试前分别等待的秒数
GAP_BETWEEN_CALLS = 6                  # 两次调用之间的固定间隔秒数


def _one_request(api_key, content, timeout=120):
    """真正发一次HTTP请求，返回(response对象或异常说明)。"""
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.1,
        "max_tokens": 1024,
    }
    headers = {"Authorization": "Bearer %s" % api_key,
               "Content-Type": "application/json"}
    try:
        return requests.post(API_URL, headers=headers, json=payload,
                             timeout=timeout), None
    except requests.exceptions.Timeout:
        return None, "请求超时(%d秒无响应)，请检查网络" % timeout
    except requests.exceptions.ConnectionError:
        return None, "无法连接 open.bigmodel.cn，请检查网络"


def call_vlm(api_key, image_paths, timeout=120, label=""):
    """调用一次模型（带429自动等待重试），返回一条可入库的记录（不含Key）。"""
    content = []
    for p in image_paths:
        content.append({"type": "image_url",
                        "image_url": {"url": image_to_data_url(p)}})
    content.append({"type": "text", "text": QUESTION})

    t0 = time.time()
    retries_used = 0
    attempt = 0
    while True:
        r, net_error = _one_request(api_key, content, timeout)
        if net_error:
            return _fail_record(None, time.time() - t0, net_error)

        if r.status_code == 200:
            try:
                data = r.json()
            except ValueError:
                return _fail_record(200, time.time() - t0,
                                    "返回了无法解析的内容: %s" % r.text[:150],
                                    retries_used)
            text = ""
            try:
                text = data["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError):
                pass
            return {
                "success": bool(text.strip()),
                "http_status": 200,
                "latency_ms": round((time.time() - t0) * 1000),
                "model": data.get("model", MODEL),
                "usage": data.get("usage", {}),
                "content_preview": text[:200],
                "retries_used": retries_used,
                "error": None if text.strip() else "返回内容为空",
            }

        # 需要重试的情况：429限流 / 5xx服务端错误
        if (r.status_code == 429 or r.status_code >= 500) \
                and attempt < len(RETRY_BACKOFF_SECONDS):
            wait = RETRY_BACKOFF_SECONDS[attempt]
            print("      ...被限流/服务端繁忙(%d)，等待%d秒后自动重试" %
                  (r.status_code, wait))
            time.sleep(wait)
            retries_used += 1
            attempt += 1
            continue

        # 不重试的失败：把常见HTTP错误翻译成人话
        hints = {
            401: "Key无效或没权限(401)：检查.env里的Key是否复制完整（格式是两段中间一个点）",
            429: "触发限流(429)：已自动重试%d次仍失败，稍后手动重跑" % retries_used,
            400: "请求格式被拒绝(400)",
            500: "智谱服务端错误(500)",
            503: "服务暂不可用(503)",
        }
        hint = hints.get(r.status_code, "HTTP %s" % r.status_code)
        detail = ""
        try:
            detail = r.json().get("error", {}).get("message", "")
        except ValueError:
            detail = r.text[:150]
        return _fail_record(r.status_code, time.time() - t0,
                            "%s | %s" % (hint, detail), retries_used)


def _fail_record(status, seconds, error, retries_used=0):
    return {"success": False, "http_status": status,
            "latency_ms": round(seconds * 1000), "model": MODEL,
            "usage": {}, "content_preview": "",
            "retries_used": retries_used, "error": error}


def describe(record):
    if record["success"]:
        return "成功  耗时%5dms  %s" % (record["latency_ms"],
                                        record["content_preview"].replace("\n", " ")[:60])
    return "失败  %s" % (record["error"] or "未知错误")


def main():
    images = sys.argv[1:]
    if not images:
        sys.exit("[用法] python scripts/01_smoke_test.py 图片1.jpg [图片2.jpg ...]\n"
                 "至少给1张图片；给2张以上会额外做一次多图测试。")

    api_key = load_api_key()
    print("=" * 60)
    print("冒烟测试开始  模型: %s  时间: %s" % (MODEL, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    print("Key已加载(脱敏显示): %s****" % api_key[:4])
    print("测试图片: %s" % ", ".join(Path(i).name for i in images))
    print("=" * 60)

    records = []

    print("\n[阶段1] 单图调用 ...")
    rec = call_vlm(api_key, [images[0]])
    records.append({"phase": "single", "images": [Path(images[0]).name],
                    "result": rec})
    print("  -> " + describe(rec))

    if len(images) >= 2:
        print("\n[阶段2] 多图调用（%d张一次发给模型）..." % len(images))
        rec = call_vlm(api_key, images)
        records.append({"phase": "multi", "images": [Path(i).name for i in images],
                        "result": rec})
        print("  -> " + describe(rec))
    else:
        print("\n[阶段2] 跳过（只给了1张图，多图测试需要2张以上）")

    print("\n[阶段3] 连续调用5次（方案要求5次全成功；限流会自动等待重试）...")
    five_ok = True
    for i in range(5):
        rec = call_vlm(api_key, [images[0]])
        records.append({"phase": "five_consecutive", "call_no": i + 1,
                        "images": [Path(images[0]).name], "result": rec})
        print("  第%d次 -> %s" % (i + 1, describe(rec)))
        if not rec["success"]:
            five_ok = False
            break  # 有一次失败就没必要继续烧调用次数
        if i < 4:
            time.sleep(GAP_BETWEEN_CALLS)  # 主动放慢节奏，减少被限流

    total = len(records)
    ok = sum(1 for r in records if r["result"]["success"])
    latencies = [r["result"]["latency_ms"] for r in records if r["result"]["success"]]

    print("\n" + "=" * 60)
    print("总结: %d/%d 次调用成功" % (ok, total))
    if latencies:
        print("成功调用耗时: 平均%dms / 最长%dms" % (
            sum(latencies) // len(latencies), max(latencies)))
    if five_ok and sum(1 for r in records if r["phase"] == "five_consecutive") == 5:
        print("[通过] 已达成方案2.3「连续5次调用成功」标准，可以进入提示词测试阶段")
    else:
        print("[未通过] 5次连续调用没有全部成功，把上面的报错发给我，我帮你排查")

    # 保存记录（自动去除Key，只留脱敏前缀）
    log = {
        "test_name": "smoke_test",
        "date": datetime.now().isoformat(timespec="seconds"),
        "model": MODEL,
        "api_endpoint": API_URL,
        "key_masked": api_key[:4] + "****",
        "prompt_version": "smoke-v0（冒烟测试临时提问，非冻结版）",
        "temperature": 0.1,
        "retry_policy": {"on_429_or_5xx_backoff_seconds": RETRY_BACKOFF_SECONDS,
                         "gap_between_calls_seconds": GAP_BETWEEN_CALLS},
        "question": QUESTION,
        "images": [{"file": Path(i).name, "sha256_16": file_sha256(i),
                    "size_kb": Path(i).stat().st_size // 1024} for i in images],
        "records": records,
        "summary": {"total": total, "ok": ok,
                    "total_retries": sum(r["result"].get("retries_used", 0)
                                         for r in records),
                    "five_consecutive_all_success": five_ok and len(
                        [r for r in records if r["phase"] == "five_consecutive"]) == 5},
    }
    out = ROOT / "logs" / ("smoke_test_%s.json" %
                           datetime.now().strftime("%Y%m%d_%H%M%S"))
    out.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n记录已保存: %s（已确认不含Key）" % out.relative_to(ROOT))


if __name__ == "__main__":
    main()
