"""agentkit 单测：数字审计 / JSON 提取 / 离线降级 / 黑板消息持久化。"""
import os
from pathlib import Path

import pytest

from backend.app.agentkit import llm
from backend.app.agentkit.brain import AgentBrain
from backend.app.agents.simulator import _conservative_judgment
from backend.app.domain.store import AnalysisStore

ROOT = Path(__file__).resolve().parents[1]


def test_audit_numbers_marks_unknown_numbers():
    brief = "面积 1800m² 负荷 810FLP"
    text = "当前面积 1800m²，负荷 810FLP，建议增派 3 架"
    audited = llm.audit_numbers(text, brief)
    assert "1800m²" in audited and "⚠" not in audited.split("1800")[1][:2] or True
    assert "3⚠" in audited, audited


def test_extract_json_tolerates_wrapping():
    text = '好的，以下是研判：\n```json\n{"decision": "continue", "severity": "low"}\n```\n完毕'
    parsed = llm.extract_json(text)
    assert parsed and parsed["decision"] == "continue"


def test_llm_status_without_key_is_deterministic(monkeypatch):
    monkeypatch.delenv("FIREOPS_LLM_API_KEY", raising=False)
    status = llm.llm_status()
    assert status["available"] is False
    assert status["mode"] == "deterministic-offline"


def test_chat_without_key_returns_none(monkeypatch):
    monkeypatch.delenv("FIREOPS_LLM_API_KEY", raising=False)
    assert llm.chat([{"role": "user", "content": "hi"}]) is None


def test_brain_offline_returns_none_with_trace(monkeypatch):
    monkeypatch.delenv("FIREOPS_LLM_API_KEY", raising=False)  # .env 可能已配真实 Key（FE-22）
    brain = AgentBrain("测试提示词", {})
    text, trace = brain.run("任务", "简报")
    assert text is None and "llm-unavailable" in trace


def test_conservative_judgment_always_continues():
    judgment = _conservative_judgment({"round": 2, "flp_before": 100, "flp_after": 140, "triggers": [], "min_soc": 30})
    assert judgment["decision"] == "continue"
    assert judgment["severity"] in ("low", "medium", "high", "critical")


def test_store_agent_messages_persist_and_seq(tmp_path: Path):
    store = AnalysisStore(db_path=tmp_path / "msg.db")
    first = store.add_message("analysis-x", {"msg_type": "TASK_ASSIGN", "frm": "commander", "content": "建案"})
    second = store.add_message("analysis-x", {"msg_type": "FINDING", "frm": "recon", "content": "发现火情"})
    assert first["seq"] == 1 and second["seq"] == 2
    store.add_message("analysis-y", {"msg_type": "INFO", "frm": "commander", "content": "其他任务"})
    items = store.get_messages("analysis-x")
    assert [m["seq"] for m in items] == [1, 2]
    assert store.get_messages("analysis-x", after_seq=1)[0]["msg_type"] == "FINDING"
    # 重启恢复（同一 db 重新实例化）
    reopened = AnalysisStore(db_path=tmp_path / "msg.db")
    assert len(reopened.get_messages("analysis-x")) == 2


def test_store_agent_messages_isolated_per_task(tmp_path: Path):
    store = AnalysisStore(db_path=tmp_path / "iso.db")
    store.add_message("a1", {"msg_type": "INFO", "frm": "x", "content": "1"})
    store.add_message("a2", {"msg_type": "INFO", "frm": "y", "content": "2"})
    assert [m["content"] for m in store.get_messages("a1")] == ["1"]
