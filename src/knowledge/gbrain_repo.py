"""Gbraph-backed knowledge repository.

Wraps the gbrain bridge HTTP API to provide KnowledgeEntry-compatible
CRUD operations with ACL support.

Usage::

    from src.knowledge.gbrain_repo import GbrainKnowledgeRepository
    repo = GbrainKnowledgeRepository()
    repo.save(entry)
    results = repo.search_accessible("keyword", user_id="user_xxx")
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any

from src.knowledge.contracts import KnowledgeEntry, KnowledgeOwnerType

logger = logging.getLogger(__name__)

GBRAIN_URL = "http://127.0.0.1:8787/mcp"


def _rpc(method: str, params: dict[str, Any]) -> Any:
    """Call gbrain JSON-RPC endpoint and return result."""
    body = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}).encode("utf-8")
    req = urllib.request.Request(GBRAIN_URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        resp_data = json.loads(resp.read().decode("utf-8"))
    if "error" in resp_data:
        raise RuntimeError(f"gbrain RPC error: {resp_data['error']}")
    return resp_data.get("result")


def _entry_from_gbrain_row(row: dict) -> KnowledgeEntry:
    """Convert a gbrain page dict to a KnowledgeEntry."""
    fm = row.get("frontmatter", {})
    if isinstance(fm, str):
        fm = json.loads(fm)
    return KnowledgeEntry(
        id=row["id"],
        owner_type=KnowledgeOwnerType(fm.get("owner_type", "personal")),
        owner_id=fm.get("owner_id", row["id"]),
        content=row.get("content", ""),
        tags=row.get("tags", []),
        metadata={k: v for k, v in fm.items() if k not in ("owner_type", "owner_id")},
        read_roles=list(row.get("read_roles", ["*"])),
        write_roles=list(row.get("write_roles", ["admin"])),
    )


def _frontmatter_from_entry(entry: KnowledgeEntry) -> dict[str, Any]:
    """Build frontmatter dict from KnowledgeEntry fields."""
    fm = dict(entry.metadata)
    fm["owner_type"] = entry.owner_type.value
    fm["owner_id"] = entry.owner_id
    return fm


class GbrainKnowledgeRepository:
    """Knowledge repository backed by gbrain/PostgreSQL.

    Implements the same interface as FtsKnowledgeRepository but via
    HTTP calls to the gbrain bridge.
    """

    def save(self, entry: KnowledgeEntry) -> KnowledgeEntry:
        _rpc("put_page", {
            "id": entry.id,
            "title": entry.content[:80],
            "content": entry.content,
            "tags": entry.tags,
            "read_roles": entry.read_roles or ["*"],
            "write_roles": entry.write_roles or ["admin"],
            "frontmatter": _frontmatter_from_entry(entry),
        })
        return entry

    def get(self, entry_id: str) -> KnowledgeEntry | None:
        row = _rpc("get_page", {"id": entry_id})
        if not row:
            return None
        return _entry_from_gbrain_row(row)

    def search(self, query: str, limit: int = 20) -> list[KnowledgeEntry]:
        rows = _rpc("search", {"query": query, "limit": limit})
        return [_entry_from_gbrain_row(r) for r in rows]

    def search_accessible(self, query: str, user_id: str = "", limit: int = 20) -> list[KnowledgeEntry]:
        rows = _rpc("search", {"query": query, "user_id": user_id, "limit": limit})
        return [_entry_from_gbrain_row(r) for r in rows]

    def list_for_owner(self, owner_type: KnowledgeOwnerType, owner_id: str) -> list[KnowledgeEntry]:
        rows = _rpc("list_for_owner", {
            "owner_type": owner_type.value,
            "owner_id": owner_id,
        })
        return [_entry_from_gbrain_row(r) for r in rows]

    def list_accessible(self, user_id: str = "") -> list[KnowledgeEntry]:
        """Return all entries the user can read (org + personal)."""
        rows = _rpc("search", {"query": "", "user_id": user_id, "limit": 200})
        return [_entry_from_gbrain_row(r) for r in rows]

    def delete(self, entry_id: str, user_id: str = "") -> bool:
        try:
            _rpc("delete_page", {"id": entry_id, "user_id": user_id})
            return True
        except Exception as e:
            logger.warning("Failed to delete %s: %s", entry_id, e)
            return False
