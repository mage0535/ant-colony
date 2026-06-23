from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from src.memory.warm_store import WarmMemoryStore

logger = logging.getLogger(__name__)

_ENTITY_PATTERNS = [
    (re.compile(r"(\S{2,8})(?:投资|收购|入股)(\S{2,8})"), "invested_in"),
    (re.compile(r"(\S{2,8})(?:在|于)(\S{2,8})(?:工作|任职)"), "works_at"),
    (re.compile(r"(\S{2,8})(?:创建|开发|开发了|写了)(\S{2,8})"), "created"),
    (re.compile(r"(\S{2,8})(?:负责|管理|维护)(\S{2,8})"), "manages"),
    (re.compile(r"(\S{2,8})(?:依赖|依赖了|需要)(\S{2,8})"), "depends_on"),
]


class ColdKnowledgeGraph:
    """Cold-layer knowledge graph backed by SQLite (replaces gbrain/PostgreSQL).

    Stores nodes (entities/concepts) and edges (relations) with FTS5 search.
    Supports wikilinks-style entity extraction from Chinese text.
    """

    def __init__(self, db_conn: Any) -> None:
        self._conn = db_conn
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS kg_nodes (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                node_type TEXT NOT NULL DEFAULT 'concept',
                properties TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL DEFAULT (cast(strftime('%s','now') as real))
            )"""
        )
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS kg_edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relation TEXT NOT NULL DEFAULT 'related_to',
                weight REAL NOT NULL DEFAULT 1.0,
                created_at REAL NOT NULL DEFAULT (cast(strftime('%s','now') as real))
            )"""
        )
        self._conn.execute(
            """CREATE VIRTUAL TABLE IF NOT EXISTS kg_nodes_fts
               USING fts5(id, label, node_type, content='kg_nodes', content_rowid='rowid')"""
        )
        self._conn.commit()

    def add_node(self, node_id: str, label: str, node_type: str = "concept",
                 properties: dict[str, Any] | None = None) -> str:
        props_json = json.dumps(properties or {}, ensure_ascii=False)
        self._conn.execute(
            "INSERT OR REPLACE INTO kg_nodes (id, label, node_type, properties) VALUES (?, ?, ?, ?)",
            (node_id, label, node_type, props_json),
        )
        self._conn.execute(
            "INSERT INTO kg_nodes_fts (id, label, node_type) VALUES (?, ?, ?)",
            (node_id, label, node_type),
        )
        self._conn.commit()
        return node_id

    def add_edge(self, source: str, target: str, relation: str = "related_to", weight: float = 1.0) -> int:
        cur = self._conn.execute(
            "INSERT INTO kg_edges (source_id, target_id, relation, weight) VALUES (?, ?, ?, ?)",
            (source, target, relation, weight),
        )
        self._conn.commit()
        return cur.lastrowid or 0

    def extract_and_ingest(self, text: str, domain: str = "general") -> int:
        count = 0
        for pattern, relation in _ENTITY_PATTERNS:
            for match in pattern.finditer(text):
                subj = match.group(1)
                obj = match.group(2)
                sid = f"e:{_safe_id(subj)}"
                tid = f"e:{_safe_id(obj)}"
                self.add_node(sid, subj, "entity")
                self.add_node(tid, obj, "entity")
                self.add_edge(sid, tid, relation)
                count += 1
        if count > 0:
            logger.info("ColdKG: extracted %d relations from text (domain=%s)", count, domain)
        return count

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT kn.* FROM kg_nodes kn JOIN kg_nodes_fts knf ON kn.id = knf.id "
            "WHERE kg_nodes_fts MATCH ? LIMIT ?",
            (query, limit),
        ).fetchall()
        return [{"id": r["id"], "label": r["label"], "type": r["node_type"],
                 "properties": json.loads(r["properties"])} for r in rows]

    def get_neighbors(self, node_id: str, depth: int = 1) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for d in range(depth):
            rows = self._conn.execute(
                "SELECT e.*, n2.label as target_label FROM kg_edges e "
                "JOIN kg_nodes n2 ON e.target_id = n2.id WHERE e.source_id = ?",
                (node_id,),
            ).fetchall()
            for r in rows:
                results.append({
                    "source": node_id,
                    "target": r["target_id"],
                    "target_label": r["target_label"],
                    "relation": r["relation"],
                    "weight": r["weight"],
                })
        return results

    def stats(self) -> dict[str, Any]:
        nodes = self._conn.execute("SELECT COUNT(*) as c FROM kg_nodes").fetchone()
        edges = self._conn.execute("SELECT COUNT(*) as c FROM kg_edges").fetchone()
        return {"nodes": nodes["c"] if nodes else 0, "edges": edges["c"] if edges else 0}


def _safe_id(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()[:16]

# ---- Tiered Context Injector ----

class TieredContextInjector:
    """Recall engine: Hot → Warm → Cold fusion (RRF k=60 compatible).

    Queries all three memory layers and fuses results into a single
    context block for injection into agent system prompts.
    """

    def __init__(self, warm: WarmMemoryStore, cold: ColdKnowledgeGraph) -> None:
        self.warm = warm
        self.cold = cold

    def recall(self, query: str, domain: str = "", top_k: int = 10) -> dict[str, Any]:
        warm_results = self.warm.recall(query, limit=top_k, domain=domain) if domain else self.warm.recall(query, limit=top_k)
        cold_results = self.cold.search(query, limit=top_k)

        # Simple fusion: interleave warm + cold, deduplicate by content
        fused = []
        seen: set[str] = set()
        for r in warm_results:
            if r["content"] not in seen:
                fused.append({"source": "warm", **r})
                seen.add(r["content"])
        for r in cold_results:
            key = r["label"]
            if key not in seen:
                fused.append({"source": "cold", "content": r["label"], "type": r["type"], **r})
                seen.add(key)

        return {
            "query": query,
            "domain": domain,
            "warm_count": len(warm_results),
            "cold_count": len(cold_results),
            "fused_count": len(fused),
            "results": fused[:top_k],
        }

    def build_context_block(self, query: str, domain: str = "") -> str:
        result = self.recall(query, domain)
        lines = [f"## 记忆检索: {query}"]
        for r in result["results"]:
            source_label = {"warm": "🧠 近期", "cold": "📚 知识"}.get(r.get("source", ""), "💾")
            content = r.get("content", r.get("label", ""))[:200]
            lines.append(f"- {source_label}: {content}")
        return "\n".join(lines)
