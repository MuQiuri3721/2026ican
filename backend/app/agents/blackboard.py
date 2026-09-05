"""黑板消息协议与发布：Agent 间不直接对话，全部经 store.add_message 协作。"""
from datetime import datetime
from typing import Any, Dict, Optional

MSG_TYPES = (
    "TASK_ASSIGN", "FINDING", "PLAN_PROPOSAL", "SIM_RESULT", "APPROVAL_REQ", "APPROVAL_DECISION",
    "ROUND", "JUDGMENT", "REPLAN_TRIGGER", "REPORT", "BACKFILL", "EVAC_BROADCAST", "INFO", "ERROR",
)


def post_message(analysis_id: str, msg_type: str, frm: str, to: str, content: str,
                 data: Optional[Dict[str, Any]] = None, source: str = "agent") -> Optional[Dict[str, Any]]:
    """发布协作消息；任务不存在（已被清理）时静默返回 None，绝不阻塞主管线。"""
    from ..domain.store import analysis_store

    try:
        return analysis_store.add_message(analysis_id, {
            "msg_type": msg_type,
            "frm": frm,
            "to": to,
            "content": content,
            "data": data or {},
            "source": source,
            "ts": datetime.now().isoformat(timespec="seconds"),
        })
    except KeyError:
        return None
    except Exception:
        return None
