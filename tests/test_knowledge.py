"""经验知识库（FE-27）：切块索引、检索命中、HTTP 端点契约。"""
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.knowledge import knowledge_stats, query_knowledge


def test_knowledge_index_built_from_sources():
    stats = knowledge_stats()
    assert stats["chunks_total"] > 0
    keys = {s["key"] for s in stats["sources"]}
    assert {"rules", "experience"} <= keys  # 规则与处置经验两份核心文档必须入库


def test_query_hits_experience_and_rules():
    hit = query_knowledge("单机失能怎么处置", top_k=3)
    assert hit["ok"] and hit["results"], "处置经验检索应有命中"
    assert any(r["source"] in ("experience", "rules") for r in hit["results"])
    empty = query_knowledge("   ")
    assert empty["ok"] is False


def test_knowledge_endpoint_contract():
    client = TestClient(app)
    stats = client.get("/api/knowledge")
    assert stats.status_code == 200
    assert "chunks_total" in stats.json()
    query = client.get("/api/knowledge", params={"query": "风况突变", "top_k": 2})
    assert query.status_code == 200
    assert query.json()["ok"] is True
