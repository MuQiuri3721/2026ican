"""经验知识库（FE-27，移植自 firepatrol-agents rules/knowledge.py，适配 2026ican 目录）。

把团队四份内置文档（参数规则 / 思路细化 / 未知险情处置经验 / PWM-Net 论文）切块建索引，
供 Agent 研判与指挥员问答接地引用——Agent 的"经验"由此而来，检索不到就明说。
纯离线实现：标题/段落分块 + 中英文关键词评分，无外部依赖；PDF 缺 pypdf 时显式告警并跳过。
"""
from __future__ import annotations

import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[3]
KNOWLEDGE_DIR = ROOT / "data" / "knowledge"

SOURCES = {
    "rules": {"file": "无人机子群与参数规则.md", "title": "无人机子群与参数规则", "loader": "text"},
    "design": {"file": "思路细化.md", "title": "项目思路细化", "loader": "text"},
    "experience": {"file": "未知险情处置经验.md", "title": "未知险情处置经验（研判参考）", "loader": "text"},
    "paper": {"file": "PWM-Net论文.pdf", "title": "PWM-Net 频域增强林火检测论文", "loader": "pdf"},
}


def _load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
        return "\n".join((page.extract_text() or "") for page in PdfReader(str(path)).pages)
    except Exception as error:  # noqa: BLE001 —— 缺 pypdf/文件损坏时论文内容跳过，但必须留痕
        print(f"[knowledge] PDF 加载失败，知识库将缺少论文内容（{path.name}）：{error}", file=sys.stderr)
        return ""


@lru_cache(maxsize=1)
def _chunks() -> List[Dict[str, Any]]:
    """切成带来源标签的知识块（标题段 + 连续正文段，每块 ≤600 字）。"""
    pieces: List[Dict[str, Any]] = []
    for key, meta in SOURCES.items():
        path = KNOWLEDGE_DIR / meta["file"]
        if not path.exists():
            continue
        text = _load_pdf(path) if meta["loader"] == "pdf" else _load_text(path)
        section = meta["title"]
        buffer: List[str] = []
        size = 0
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if re.match(r"^#{1,4}\s", line) or re.match(r"^\d+(\.\d+)*\s+\S", line) or (len(line) < 40 and not line.endswith(("。", ".", "；", ";"))):
                if buffer:
                    pieces.append({"source": key, "section": section, "text": " ".join(buffer)[:1200]})
                    buffer, size = [], 0
                section = re.sub(r"^#{1,4}\s*", "", line)[:60]
            buffer.append(line)
            size += len(line)
            if size > 600:
                pieces.append({"source": key, "section": section, "text": " ".join(buffer)[:1200]})
                buffer, size = [], 0
        if buffer:
            pieces.append({"source": key, "section": section, "text": " ".join(buffer)[:1200]})
    return pieces


def _keywords(query: str) -> List[str]:
    """中文长查询按 2-4 字 + 全部二元词切分（贪婪 4 字切分会把"单机失能"切成"单机失能怎"导致漏检）。"""
    tokens: List[str] = []
    for run in re.findall(r"[\u4e00-\u9fa5]{2,}", query):
        tokens.append(run[:4])
        tokens.extend(run[i:i + 2] for i in range(len(run) - 1))
    tokens.extend(re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", query))
    seen, out = set(), []
    for token in tokens:
        if token not in seen:
            seen.add(token)
            out.append(token)
    return out or [query]


def query_knowledge(query: str, top_k: int = 3) -> Dict[str, Any]:
    """知识检索：返回与问题最相关的文档片段（Agent/GLM 接地用，数字仍以规则引擎为准）。"""
    if not query or not query.strip():
        return {"ok": False, "error": "query 为空", "results": []}
    kws = _keywords(query)
    scored = []
    for index, chunk in enumerate(_chunks()):
        text = chunk["text"]
        score = sum(min(text.count(kw), 3) for kw in kws)
        title_hit = sum(2 for kw in kws if kw in chunk["section"])
        if score + title_hit > 0:
            scored.append((score + title_hit, index, chunk))
    scored.sort(key=lambda item: (-item[0], item[1]))
    results = [{"source": c["source"], "source_name": SOURCES[c["source"]]["title"],
                "section": c["section"], "text": c["text"], "score": s} for s, _, c in scored[: max(1, min(top_k, 6))]]
    return {"ok": bool(results), "query": query, "matched": len(scored),
            "results": results, "source": "knowledge-base-tool"}


def knowledge_stats() -> Dict[str, Any]:
    chunks = _chunks()
    by_source: Dict[str, int] = {}
    for chunk in chunks:
        by_source[chunk["source"]] = by_source.get(chunk["source"], 0) + 1
    return {"sources": [{"key": k, "file": m["file"], "title": m["title"]} for k, m in SOURCES.items()],
            "chunks_total": len(chunks), "chunks_by_source": by_source}
