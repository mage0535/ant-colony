from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from typing import Any

from src.knowledge.contracts import KnowledgeEntry, KnowledgeOwnerType

logger = logging.getLogger(__name__)


class FtsKnowledgeRepository:
    """SQLite FTS5-backed knowledge store with full-text search and ACL filtering.

    Replaces InMemoryKnowledgeRepository. Supports three-tier access:
    - personal: owner_id = user_id
    - project: owner_id = project_id, accessible by any member of that project
    - organization: owner_id = "*", accessible by all
    """

    def __init__(self, db_conn: Any) -> None:
        self._conn = db_conn
        self._init_fts()

    def _init_fts(self) -> None:
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS knowledge_items (
                id TEXT PRIMARY KEY,
                owner_type TEXT NOT NULL,
                owner_id TEXT NOT NULL,
                content TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '[]',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                read_roles TEXT NOT NULL DEFAULT '["self"]',
                write_roles TEXT NOT NULL DEFAULT '["admin","self"]',
                created_at REAL NOT NULL DEFAULT (cast(strftime('%s','now') as real))
            )"""
        )
        self._conn.execute(
            """CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts
               USING fts5(id, owner_type, owner_id, content, tags, tokenize='unicode61')"""
        )
        # Migrate existing tables missing ACL columns
        for col, default_val in [("read_roles", '["self"]'), ("write_roles", '["admin","self"]')]:
            try:
                self._conn.execute(
                    f"ALTER TABLE knowledge_items ADD COLUMN {col} TEXT NOT NULL DEFAULT '{default_val}'"
                )
            except Exception:
                pass
        self._conn.commit()

    def save(self, entry: KnowledgeEntry) -> KnowledgeEntry:
        tags_json = json.dumps(entry.tags, ensure_ascii=False)
        meta_json = json.dumps(entry.metadata, ensure_ascii=False)
        # Store ACL roles as JSON strings
        read_roles_json = json.dumps(entry.read_roles or ["self"], ensure_ascii=False)
        write_roles_json = json.dumps(entry.write_roles or ["admin", "self"], ensure_ascii=False)
        self._conn.execute(
            """INSERT OR REPLACE INTO knowledge_items
               (id, owner_type, owner_id, content, tags, metadata_json, read_roles, write_roles)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (entry.id, entry.owner_type.value, entry.owner_id, entry.content,
             tags_json, meta_json, read_roles_json, write_roles_json),
        )
        self._conn.execute("DELETE FROM knowledge_fts WHERE id = ?", (entry.id,))
        self._conn.execute(
            "INSERT INTO knowledge_fts (id, owner_type, owner_id, content, tags) VALUES (?, ?, ?, ?, ?)",
            (entry.id, entry.owner_type.value, entry.owner_id, entry.content, tags_json),
        )
        self._conn.commit()
        return entry

    def get(self, entry_id: str) -> KnowledgeEntry | None:
        row = self._conn.execute(
            "SELECT * FROM knowledge_items WHERE id = ?",
            (entry_id,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_entry(row)

    def list_for_owner(self, owner_type: KnowledgeOwnerType, owner_id: str) -> list[KnowledgeEntry]:
        rows = self._conn.execute(
            "SELECT * FROM knowledge_items WHERE owner_type = ? AND owner_id = ? ORDER BY created_at DESC",
            (owner_type.value, owner_id),
        ).fetchall()
        return [_row_to_entry(r) for r in rows]

    def search(self, query: str, user_id: str = "", space_id: str = "", limit: int = 20) -> list[KnowledgeEntry]:
        rows = self._query_rows(query, limit)
        return [_row_to_entry(r) for r in rows if _acl_check(r, user_id, space_id)]

    def search_accessible(self, query: str, user_id: str, space_id: str = "", limit: int = 20) -> list[KnowledgeEntry]:
        """Search knowledge with ACL filtering — only returns entries the user may read.
        
        Uses resolve_role() + may_read() from src.knowledge.acl to enforce per-entry access.
        """
        from src.knowledge.acl import resolve_role, may_read, visible_scopes, Role

        role = resolve_role(user_id, space_id)

        # Fetch more rows than limit; ACL may filter some out
        fetch_limit = limit * 3 if limit > 0 else 60
        rows = self._query_rows(query, fetch_limit)

        results: list[KnowledgeEntry] = []
        for r in rows:
            entry = _row_to_entry(r)
            if may_read(role, entry.owner_type.value, entry.owner_id, user_id):
                results.append(entry)
                if len(results) >= limit:
                    break
        return results

    def _query_rows(self, query: str, limit: int) -> list[Any]:
        try:
            return self._conn.execute(
                """SELECT ki.* FROM knowledge_items ki
                   JOIN knowledge_fts kf ON ki.id = kf.id
                   WHERE knowledge_fts MATCH ?
                   LIMIT ?""",
                (query, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            logger.warning("FTS query failed for %r, falling back to LIKE search", query)
            terms = [part.strip() for part in re.split(r"[^\w\u4e00-\u9fff]+", query) if part.strip()]
            search_terms = terms or [query]
            clauses = []
            params: list[Any] = []
            for term in search_terms[:8]:
                clauses.append("(content LIKE ? OR tags LIKE ? OR metadata_json LIKE ?)")
                wildcard = f"%{term}%"
                params.extend([wildcard, wildcard, wildcard])
            return self._conn.execute(
                f"""SELECT * FROM knowledge_items
                   WHERE {" OR ".join(clauses)}
                   ORDER BY created_at DESC
                   LIMIT ?""",
                [*params, limit],
            ).fetchall()

    def list_accessible(self, user_id: str, limit: int = 50) -> list[KnowledgeEntry]:
        """List all knowledge entries the user may read, ordered by creation time."""
        from src.knowledge.acl import resolve_role, may_read, visible_scopes, Role

        role = resolve_role(user_id, "")

        rows = self._conn.execute(
            "SELECT * FROM knowledge_items ORDER BY created_at DESC LIMIT ?",
            (limit * 2,),
        ).fetchall()

        results: list[KnowledgeEntry] = []
        for r in rows:
            entry = _row_to_entry(r)
            if may_read(role, entry.owner_type.value, entry.owner_id, user_id):
                results.append(entry)
                if len(results) >= limit:
                    break
        return results

    def delete(self, entry_id: str, user_id: str = "") -> bool:
        # ACL permission check before deletion
        if user_id:
            from src.knowledge.acl import resolve_role, may_write
            row = self._conn.execute(
                "SELECT owner_type, owner_id FROM knowledge_items WHERE id = ?", (entry_id,)
            ).fetchone()
            if row is None:
                return False
            role = resolve_role(user_id, "")
            if not may_write(role, row["owner_type"], row["owner_id"], user_id):
                return False
        cur = self._conn.execute("DELETE FROM knowledge_items WHERE id = ?", (entry_id,))
        self._conn.execute("DELETE FROM knowledge_fts WHERE id = ?", (entry_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def stats(self) -> dict[str, Any]:
        total = self._conn.execute("SELECT COUNT(*) as c FROM knowledge_items").fetchone()
        per_type = self._conn.execute(
            "SELECT owner_type, COUNT(*) as c FROM knowledge_items GROUP BY owner_type"
        ).fetchall()
        return {
            "total_entries": total["c"] if total else 0,
            "by_type": {r["owner_type"]: r["c"] for r in per_type},
        }


def _acl_check(row: Any, user_id: str, space_id: str) -> bool:
    owner_type = row["owner_type"]
    owner_id = row["owner_id"]
    if not user_id and not space_id:
        return True
    if owner_type == KnowledgeOwnerType.ORGANIZATION.value:
        return True
    if owner_type == KnowledgeOwnerType.PERSONAL.value and (not user_id or owner_id == user_id):
        return True
    if owner_type in (KnowledgeOwnerType.PROJECT.value, KnowledgeOwnerType.DEPARTMENT.value) and (not space_id or owner_id == space_id):
        return True
    return False


def _row_to_entry(row: Any) -> KnowledgeEntry:
    return KnowledgeEntry(
        id=row["id"],
        owner_type=KnowledgeOwnerType(row["owner_type"]),
        owner_id=row["owner_id"],
        content=row["content"],
        tags=json.loads(row["tags"]),
        metadata=json.loads(row["metadata_json"]),
        read_roles=json.loads(row["read_roles"] if "read_roles" in row.keys() else '["self"]'),
        write_roles=json.loads(row["write_roles"] if "write_roles" in row.keys() else '["admin","self"]'),
    )
