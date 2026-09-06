# -*- coding: utf-8 -*-
"""vlm_api.py — 调用智谱标准API的公共模块（所有测试脚本共用）"""
import base64
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.stdout.reconfigure(encoding="utf-8")

API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
MODEL = "glm-4.6v-flash"

# 限流退避策略（实测2026-09-06：间隔6秒；晚高峰429频繁，12/25/50三档仍偶有耗尽，加长为4档）
RETRY_BACKOFF_SECONDS = [15, 40, 90, 150]
GAP_BETWEEN_CALLS = 6


def load_api_key():
    """从项目根目录 .env 读取标准API Key。"""
    env_path = ROOT / ".env"
    if not env_path.exists():
        sys.exit("[错误] 找不到 .env 文件: %s" % env_path)
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("ZHIPU_API_KEY="):
            key = line.split("=", 1)[1].strip().strip('"').strip("'")
            if not key or not key.isascii() or key == "your_api_key_here":
                sys.exit("[错误] .env 里的 Key 还没换成真实的。")
            return key
    sys.exit("[错误] .env 里没有 ZHIPU_API_KEY= 这一行。")


def image_to_data_url(path):
    """本地图片 -> data:image/...;base64,... （模型直接读图，不依赖外链）"""
    p = Path(path)
    if not p.exists():
        sys.exit("[错误] 图片不存在: %s" % p)
    suffix = p.suffix.lower().lstrip(".")
    if suffix in ("jpg", "jpeg"):
        mime = "jpeg"
    elif suffix == "png":
        mime = "png"
    else:
        sys.exit("[错误] 只支持 jpg/png: %s" % p.name)
    size_mb = p.stat().st_size / 1024 / 1024
    if size_mb > 4.5:
        sys.exit("[错误] 图片 %s 太大(%.1fMB)，请先压缩" % (p.name, size_mb))
    return "data:image/%s;base64,%s" % (
        mime, base64.b64encode(p.read_bytes()).decode())


def chat(api_key, messages, temperature=0.1, max_tokens=2048,
         model=MODEL, timeout=180):
    """调用一次模型（自动处理429/5xx退避重试）。返回记录dict，不含Key。"""
    payload = {"model": model, "messages": messages,
               "temperature": temperature, "max_tokens": max_tokens}
    headers = {"Authorization": "Bearer %s" % api_key,
               "Content-Type": "application/json"}
    t0 = time.time()
    attempt, retries_used = 0, 0
    while True:
        try:
            r = requests.post(API_URL, headers=headers, json=payload,
                              timeout=timeout)
        except requests.exceptions.Timeout:
            return _fail(None, time.time() - t0,
                         "请求超时(%d秒)，请检查网络" % timeout, retries_used)
        except requests.exceptions.ConnectionError:
            return _fail(None, time.time() - t0,
                         "无法连接 open.bigmodel.cn", retries_used)

        if r.status_code == 200:
            try:
                data = r.json()
            except ValueError:
                return _fail(200, time.time() - t0,
                             "返回无法解析: %s" % r.text[:150], retries_used)
            text = ""
            try:
                text = data["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError):
                pass
            return {"success": bool(text.strip()), "http_status": 200,
                    "latency_ms": round((time.time() - t0) * 1000),
                    "model": data.get("model", model),
                    "usage": data.get("usage", {}), "content": text,
                    "retries_used": retries_used, "error":
                        None if text.strip() else "返回内容为空"}

        if (r.status_code == 429 or r.status_code >= 500) \
                and attempt < len(RETRY_BACKOFF_SECONDS):
            wait = RETRY_BACKOFF_SECONDS[attempt]
            print("      ...限流/服务端繁忙(%d)，等%d秒自动重试" %
                  (r.status_code, wait), flush=True)
            time.sleep(wait)
            retries_used += 1
            attempt += 1
            continue

        hints = {401: "Key无效(401)", 429: "限流(429)，重试%d次后仍失败" % retries_used,
                 400: "请求格式错误(400)", 500: "服务端错误(500)", 503: "服务不可用(503)"}
        hint = hints.get(r.status_code, "HTTP %s" % r.status_code)
        detail = ""
        try:
            detail = r.json().get("error", {}).get("message", "")
        except ValueError:
            detail = r.text[:150]
        return _fail(r.status_code, time.time() - t0,
                     "%s | %s" % (hint, detail), retries_used)


def _fail(status, seconds, error, retries_used=0):
    return {"success": False, "http_status": status,
            "latency_ms": round(seconds * 1000), "model": MODEL,
            "usage": {}, "content": "", "retries_used": retries_used,
            "error": error}


def masked_request_sample(messages, max_b64=48):
    """生成去密钥、截断Base64的请求样例（用于交付文档）。"""
    import copy
    sample = copy.deepcopy(messages)
    for msg in sample:
        if isinstance(msg.get("content"), list):
            for part in msg["content"]:
                if part.get("type") == "image_url":
                    url = part["image_url"]["url"]
                    if url.startswith("data:"):
                        part["image_url"]["url"] = (
                            url[:36] + "...[BASE64已省略,全长%d字符]" % len(url))
    return {"model": MODEL, "messages": sample, "temperature": 0.1,
            "max_tokens": 2048}
