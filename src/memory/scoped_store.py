from __future__ import annotations

import hashlib
import time
from typing import Any


class ScopedMemoryStore:
    """Scope-aware memory store for personal / department / project / group contexts."""

    def __init__(self, db_conn: Any) -> None:
        self._conn = db_conn
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scoped_memories (
                id TEXT PRIMARY KEY,
                scope_type TEXT NOT NULL,
                scope_id TEXT NOT NULL,
                content TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL DEFAULT (cast(strftime('%s','now') as real)),
                access_count INTEGER NOT NULL DEFAULT 0,
                last_accessed REAL NOT NULL DEFAULT 0
            )
            """
        )
        self._conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS scoped_memories_fts
            USING fts5(id, scope_type, scope_id, content, tokenize='unicode61')
            """
        )
        self._conn.commit()

    def retain(self, content: str, *, scope_type: str, scope_id: str, source: str = "") -> str:
        memory_id = f"scope-{hashlib.sha256(f'{scope_type}:{scope_id}:{content}'.encode()).hexdigest()[:16]}"
        self._conn.execute(
            """
            INSERT OR REPLACE INTO scoped_memories (id, scope_type, scope_id, content, source, last_accessed)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (memory_id, scope_type, scope_id, content, source, time.time()),
        )
        self._conn.execute(
            "INSERT OR REPLACE INTO scoped_memories_fts (id, scope_type, scope_id, content) VALUES (?, ?, ?, ?)",
            (memory_id, scope_type, scope_id, content),
        )
        self._conn.commit()
        return memory_id

    def recall(self, query: str, *, scopes: list[tuple[str, str]], limit: int = 10) -> list[dict[str, Any]]:
        if not scopes:
            return []
        clauses = []
        for scope_type, scope_id in scopes:
            clauses.append("(sm.scope_type = ? AND sm.scope_id = ?)")
        scope_params: list[Any] = []
        for scope_type, scope_id in scopes:
            scope_params.extend([scope_type, scope_id])
        sql_scope = " OR ".join(clauses)
        rows = self._conn.execute(
            f"""
            SELECT sm.*
            FROM scoped_memories sm
            JOIN scoped_memories_fts smf ON sm.id = smf.id
            WHERE scoped_memories_fts MATCH ?
              AND ({sql_scope})
            ORDER BY sm.last_accessed DESC, sm.created_at DESC
            LIMIT ?
            """,
            [query, *scope_params, limit],
        ).fetchall()
        if not rows:
            rows = self._conn.execute(
                f"""
                SELECT sm.*
                FROM scoped_memories sm
                WHERE sm.content LIKE ?
                  AND ({sql_scope})
                ORDER BY sm.last_accessed DESC, sm.created_at DESC
                LIMIT ?
                """,
                [f"%{query}%", *scope_params, limit],
            ).fetchall()
        results = []
        for row in rows:
            self._conn.execute(
                "UPDATE scoped_memories SET access_count = access_count + 1, last_accessed = ? WHERE id = ?",
                (time.time(), row["id"]),
            )
            results.append(
                {
                    "id": row["id"],
                    "scope_type": row["scope_type"],
                    "scope_id": row["scope_id"],
                    "content": row["content"],
                    "source": row["source"],
                }
            )
        self._conn.commit()
        return results

    def promote(
        self,
        *,
        source_scope_type: str,
        source_scope_id: str,
        target_scope_type: str,
        target_scope_id: str,
        query: str,
        source_label: str = "promotion",
    ) -> int:
        memories = self.recall(query, scopes=[(source_scope_type, source_scope_id)], limit=20)
        promoted = 0
        for item in memories:
            self.retain(
                item["content"],
                scope_type=target_scope_type,
                scope_id=target_scope_id,
                source=source_label,
            )
            promoted += 1
        return promoted
