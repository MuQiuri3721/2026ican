"""GLM 调用薄层（OpenAI 兼容 /chat/completions）。

无 API key 时 llm_available()=False，全系统确定性离线运行（演示永不中断）。
连续失败 ≥2 次进入 degraded，成功一次即恢复；数字审计只标注不阻断。
"""
import json
import os
import re
import threading
from typing import Any, Dict, List, Optional, Tuple

import requests

_BASE_URL = os.environ.get("FIREOPS_LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
_MODEL = os.environ.get("FIREOPS_LLM_MODEL", "glm-4-flash")
_TIMEOUT = float(os.environ.get("FIREOPS_LLM_TIMEOUT", "12"))

_LOCK = threading.Lock()
_FAILURES = 0


def _api_key() -> str:
    return os.environ.get("FIREOPS_LLM_API_KEY", "")


def llm_available() -> bool:
    with _LOCK:
        return bool(_api_key()) and _FAILURES < 2


def llm_status() -> Dict[str, Any]:
    """状态超集：同时满足 agentkit（available/mode）与 assistant 层（connected/fail_streak）口径。"""
    with _LOCK:
        degraded = _FAILURES >= 2
        streak = _FAILURES
    return {
        "connected": bool(_api_key()),
        "configured": bool(_api_key()),
        "available": llm_available(),
        "degraded": degraded,
        "fail_streak": streak,
        "model": _MODEL if _api_key() else None,
        "mode": "glm" if llm_available() else "deterministic-offline",
    }


def chat(messages: List[Dict[str, str]], max_tokens: int = 512, temperature: float = 0.3) -> Optional[str]:
    """同步调用对话端点；失败返回 None（调用方必须自带确定性降级）。"""
    global _FAILURES
    if not _api_key():
        return None
    try:
        response = requests.post(
            _BASE_URL.rstrip("/") + "/chat/completions",
            json={"model": _MODEL, "messages": messages, "max_tokens": max_tokens, "temperature": temperature},
            headers={"Authorization": f"Bearer {_api_key()}"},
            timeout=(3, _TIMEOUT),
        )
        response.raise_for_status()
        text = (response.json().get("choices") or [{}])[0].get("message", {}).get("content")
        with _LOCK:
            _FAILURES = 0
        return (text or "").strip() or None
    except Exception:
        with _LOCK:
            _FAILURES += 1
        return None


def audit_numbers(text: str, brief: str) -> str:
    """数字审计：LLM 输出中的数字必须能在输入 brief 中找到，未知数字标 ⚠（只标注不阻断）。"""
    if not text:
        return text
    allowed = {re.sub(r"[^\d.]", "", token) for token in re.split(r"\s", brief)}
    allowed = {token for token in allowed if token}

    def _mark(match: re.Match) -> str:
        token = match.group(0)
        clean = re.sub(r"[^\d.]", "", token)
        if not clean or clean in allowed or clean.rstrip("0").rstrip(".") in allowed:
            return token
        return f"{token}⚠"

    return re.sub(r"\d+(?:\.\d+)?", _mark, text)


def extract_json(text: str) -> Optional[Dict[str, Any]]:
    """从 LLM 输出中提取首个 JSON 对象（容忍 ``` 包裹与前后废话）。"""
    if not text:
        return None
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(text[start:end + 1])
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None
