"""glm-4.6v-flash 标准 API 直连客户端（docs/VLM队员执行手册.md §2/§5）。

Key 口径（手册 §2.2）：此处使用智谱开放平台**标准 API Key**（FIRE_VLM_API_KEY，私下渠道交付），
与团队 Coding Plan Key（FIREOPS_LLM_API_KEY）严格区分，二者不可混用。
无 Key 时 vlm_client_status().configured=False，调用方走确定性回退（演示永不中断）。
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from ..agentkit.llm import extract_json
from .contract import SCHEMA_VERSION
from .prompts import (
    FRAME_SEQUENCE_NOTE,
    JSON_REPAIR_INSTRUCTION,
    MISSING_FIELDS_INSTRUCTION,
    PROMPT_VERSION,
    SYSTEM_PROMPT_V4,
    USER_TEMPLATE_V4,
)

_BASE_URL = os.environ.get("FIRE_VLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
_MODEL = os.environ.get("FIRE_VLM_MODEL", "glm-4.6v-flash")
# 交付实测（48 次调用）：纯模型耗时中位 19s、最慢 51s（推理型输出），90s 为安全上限
_TIMEOUT = float(os.environ.get("FIRE_VLM_TIMEOUT", "90"))
MAX_IMAGES = 4  # 手册 §5.3：首轮 1—3 张；时间对比 2—4 张

_LOCK = threading.Lock()
_FAILURES = 0


class ImageUnreadable(Exception):
    """图片缺失或不可读（手册 §4.1：图片不可读则停止本批次，由调用方回退）。"""


def _api_key() -> str:
    return os.environ.get("FIRE_VLM_API_KEY", "")


def vlm_client_status() -> Dict[str, Any]:
    with _LOCK:
        return {
            "configured": bool(_api_key()),
            "available": bool(_api_key()) and _FAILURES < 2,
            "fail_streak": _FAILURES,
            "model": _MODEL if _api_key() else None,
            "prompt_version": PROMPT_VERSION,
            "mode": "glm-vision" if (bool(_api_key()) and _FAILURES < 2) else "deterministic-offline",
        }


def _encode_image(path: str) -> Dict[str, Any]:
    file_path = Path(path)
    if not file_path.exists():
        raise ImageUnreadable(f"图片不存在: {path}")
    try:
        data = file_path.read_bytes()
    except OSError as error:
        raise ImageUnreadable(f"图片不可读: {path} ({error})") from error
    if not data:
        raise ImageUnreadable(f"图片为空: {path}")
    mime = mimetypes.guess_type(file_path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(data).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}


def _select_sequence(paths: List[str]) -> List[str]:
    """超过 4 张时保首 3 张 + 最新 1 张，保留时间对比首尾。"""
    if len(paths) <= MAX_IMAGES:
        return paths
    return [*paths[: MAX_IMAGES - 1], paths[-1]]


def _user_text(
    image_paths: List[str],
    observation: Dict[str, Any],
    environment: Dict[str, Any],
    people_status: str,
    task_id: Optional[str],
    round_index: int,
    previous_analysis: Optional[Dict[str, Any]],
) -> str:
    frame_ids = "、".join(f"F{i + 1}:{Path(p).name}" for i, p in enumerate(image_paths))
    yolo = {
        "detections": observation.get("detections", []),
        "mode": observation.get("mode", "missing"),
        "source": observation.get("source", "missing"),
    }
    camera = {"drone_id": None, "altitude_m": None, "heading": None, "lens": None}  # 相机元数据未接入，手册 §4.1：未知写 null
    previous = None
    if isinstance(previous_analysis, dict):
        previous = previous_analysis.get("human_summary") or previous_analysis.get("summary") or None
    # 多图轮次注入帧序列说明行（交付包 prompt-v3 §三 / v4 §三）
    sequence_note = FRAME_SEQUENCE_NOTE if len(image_paths) > 1 else ""
    alarm_location = (
        observation.get("location")
        or observation.get("alarm_location")
        or environment.get("location")
        or "未知"
    )
    return USER_TEMPLATE_V4.format(
        task_id=task_id or "unknown",
        round_index=round_index,
        alarm_location=alarm_location,
        frame_ids_with_time=frame_ids or "（无）",
        frame_sequence_note=sequence_note,
        yolo_json=_compact(yolo),
        camera_json=_compact(camera),
        scene_context_json=_compact(environment),
        weather_json=_compact({
            "wind_note": "气象风由规则引擎提供，VLM 只描述 image_plane_drift",
            "observation_confidence": observation.get("confidence"),
        }),
        previous_vlm_summary_or_null=previous or "null",
    )


def _compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _incomplete_groups(payload: Dict[str, Any]) -> List[str]:
    """vlm-analysis-v1 必填字段组缺失清单（交付 §7-1：缺字段也要定向修复，不只拦非法 JSON）。"""
    groups = ("image_quality", "fire_observation", "smoke_trend", "object_clues", "review")
    missing = [group for group in groups if not isinstance(payload.get(group), dict)]
    review = payload.get("review")
    if isinstance(review, dict) and not review.get("human_summary"):
        missing.append("review.human_summary")
    return missing


def vlm_analyze_images(
    image_paths: List[str],
    *,
    observation: Optional[Dict[str, Any]] = None,
    environment: Optional[Dict[str, Any]] = None,
    people_status: str = "unknown",
    task_id: Optional[str] = None,
    round_index: int = 1,
    previous_analysis: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """调 glm-4.6v-flash 输出 vlm-analysis-v1 JSON；失败返回 None（调用方必须自带确定性降级）。

    交付包 §7：temperature 0.1 / max_tokens 2048（推理型模型，reasoning 占 completion 69%）；
    非法 JSON 允许一次"只修复 JSON 格式"重试，再失败返回 None；HTTP 200 空响应按失败处理（P07）。
    连续失败 ≥2 次进入 degraded，直接返回 None 快速走回退（成功一次即恢复，对齐 agentkit.llm 语义）。
    """
    global _FAILURES
    if not _api_key() or not image_paths:
        return None
    with _LOCK:
        if _FAILURES >= 2:
            return None
    try:
        selected = _select_sequence(list(image_paths))
        image_parts = [_encode_image(path) for path in selected]
    except ImageUnreadable:
        raise
    text = _user_text(selected, observation or {}, environment or {}, people_status, task_id, round_index, previous_analysis)
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT_V4},
        {"role": "user", "content": [*image_parts, {"type": "text", "text": text}]},
    ]
    raw = _post(messages)
    if raw is None:
        return None
    parsed = extract_json(raw)
    if parsed is None:
        # 非法 JSON：一次"只修复 JSON 格式"重试（文本会话续接，不重传图片）
        raw_retry = _post([
            *messages,
            {"role": "assistant", "content": raw[:2000]},
            {"role": "user", "content": JSON_REPAIR_INSTRUCTION},
        ])
        parsed = extract_json(raw_retry) if raw_retry else None
        if parsed is None:
            return None  # 手册 §5.3：第二次仍非法即本批失败，走确定性回退
    # 缺必填字段组（截断/格式修复后的常见残留，P01/P02）：定向补全一次；仍缺则原样上交，
    # 由契约层判 vlm_contract_invalid（api-contract §10.2：五组必填字段必须全部出现）
    if isinstance(parsed, dict) and parsed.get("schema_version") == SCHEMA_VERSION:
        missing = _incomplete_groups(parsed)
        if missing:
            raw_retry = _post([
                *messages,
                {"role": "assistant", "content": raw[:2000]},
                {"role": "user", "content": MISSING_FIELDS_INSTRUCTION.format(missing="、".join(missing))},
            ])
            parsed_retry = extract_json(raw_retry) if raw_retry else None
            if isinstance(parsed_retry, dict) and parsed_retry.get("schema_version") == SCHEMA_VERSION \
                    and not _incomplete_groups(parsed_retry):
                parsed = parsed_retry
    return parsed


def _post(messages: List[Dict[str, Any]]) -> Optional[str]:
    global _FAILURES
    try:
        response = requests.post(
            _BASE_URL.rstrip("/") + "/chat/completions",
            json={"model": _MODEL, "messages": messages, "max_tokens": 2048, "temperature": 0.1},
            headers={"Authorization": f"Bearer {_api_key()}"},
            timeout=(3, _TIMEOUT),
        )
        response.raise_for_status()
        text = (response.json().get("choices") or [{}])[0].get("message", {}).get("content")
        text = (text or "").strip()
        if not text:
            # 交付包 P07：HTTP 200 空响应按可重试失败处理，不计成功
            with _LOCK:
                _FAILURES += 1
            return None
        with _LOCK:
            _FAILURES = 0
        return text
    except Exception:
        with _LOCK:
            _FAILURES += 1
        return None
