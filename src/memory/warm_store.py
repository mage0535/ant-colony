from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class WarmMemoryStore:
    """Warm-layer memory backed by SQLite (replaces Hindsight/PostgreSQL).

    Auto-extracts facts from conversations, stores with decay scoring,
    and provides search/recall via FTS5.
    """

    def __init__(self, db_conn: Any) -> None:
        self._conn = db_conn
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS warm_facts (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT '',
                domain TEXT NOT NULL DEFAULT 'general',
                confidence REAL NOT NULL DEFAULT 0.5,
                access_count INTEGER NOT NULL DEFAULT 0,
                last_accessed REAL NOT NULL DEFAULT 0,
                created_at REAL NOT NULL DEFAULT (cast(strftime('%s','now') as real))
            )"""
        )
        self._conn.execute(
            """CREATE VIRTUAL TABLE IF NOT EXISTS warm_facts_fts
               USING fts5(id, content, domain, tokenize='unicode61')"""
        )
        self._conn.commit()

    def retain(self, text: str, source: str = "", domain: str = "general",
               confidence: float = 0.5) -> str:
        import hashlib
        fact_id = f"fact-{hashlib.sha256(text.encode()).hexdigest()[:16]}"
        self._conn.execute(
            """INSERT OR REPLACE INTO warm_facts (id, content, source, domain, confidence, last_accessed)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (fact_id, text, source, domain, confidence, time.time()),
        )
        self._conn.execute(
            "INSERT OR REPLACE INTO warm_facts_fts (id, content, domain) VALUES (?, ?, ?)",
            (fact_id, text, domain),
        )
        self._conn.commit()
        return fact_id

    def recall(self, query: str, limit: int = 20, domain: str = "") -> list[dict[str, Any]]:
        if domain:
            rows = self._conn.execute(
                "SELECT wf.* FROM warm_facts wf JOIN warm_facts_fts wfts ON wf.id = wfts.id "
                "WHERE warm_facts_fts MATCH ? AND wf.domain = ? LIMIT ?",
                (query, domain, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT wf.* FROM warm_facts wf JOIN warm_facts_fts wfts ON wf.id = wfts.id "
                "WHERE warm_facts_fts MATCH ? LIMIT ?",
                (query, limit),
            ).fetchall()
        results = []
        for r in rows:
            self._conn.execute(
                "UPDATE warm_facts SET access_count = access_count + 1, last_accessed = ? WHERE id = ?",
                (time.time(), r["id"]),
            )
            self._conn.commit()
            results.append({"id": r["id"], "content": r["content"], "domain": r["domain"],
                            "confidence": r["confidence"], "access_count": r["access_count"] + 1})
        return results

    def stats(self) -> dict[str, Any]:
        total = self._conn.execute("SELECT COUNT(*) as c FROM warm_facts").fetchone()
        by_domain = self._conn.execute(
            "SELECT domain, COUNT(*) as c FROM warm_facts GROUP BY domain"
        ).fetchall()
        return {
            "total_facts": total["c"] if total else 0,
            "by_domain": {r["domain"]: r["c"] for r in by_domain},
        }

    def decay(self, max_age_hours: int = 720) -> int:
        cutoff = time.time() - max_age_hours * 3600
        cur = self._conn.execute(
            "DELETE FROM warm_facts WHERE last_accessed < ? AND access_count < 3", (cutoff,)
        )
        count = cur.rowcount
        if count > 0:
            self._conn.commit()
            logger.info("WarmMemory decay: removed %d old facts", count)
        return count
