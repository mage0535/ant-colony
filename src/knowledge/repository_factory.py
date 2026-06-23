from __future__ import annotations

import logging
from typing import Any

from src.knowledge.contracts import KnowledgeEntry, KnowledgeOwnerType
from src.knowledge.fts_repo import FtsKnowledgeRepository
from src.store.database import Database

logger = logging.getLogger(__name__)


class UnifiedKnowledgeRepository:
    """Read/write knowledge through one interface with local fallback.

    Primary goal:
    - Bot search
    - dashboard management
    - file ingestion
    - scripted imports

    all see the same logical knowledge source.
    """

    def __init__(self, local_repo: FtsKnowledgeRepository, remote_repo: Any | None = None) -> None:
        self._local = local_repo
        self._remote = remote_repo

    def save(self, entry: KnowledgeEntry) -> KnowledgeEntry:
        self._local.save(entry)
        if self._remote is not None:
            try:
                self._remote.save(entry)
            except Exception as exc:
                logger.warning("Remote knowledge save failed for %s: %s", entry.id, exc)
        return entry

    def get(self, entry_id: str) -> KnowledgeEntry | None:
        if self._remote is not None and hasattr(self._remote, "get"):
            try:
                result = self._remote.get(entry_id)
                if result is not None:
                    return result
            except Exception as exc:
                logger.warning("Remote knowledge get failed for %s: %s", entry_id, exc)
        if hasattr(self._local, "get"):
            return self._local.get(entry_id)
        return None

    def search(self, query: str, limit: int = 20) -> list[KnowledgeEntry]:
        if self._remote is not None and hasattr(self._remote, "search"):
            try:
                results = self._remote.search(query, limit=limit)
                if results:
                    return results
            except Exception as exc:
                logger.warning("Remote knowledge search failed for %r: %s", query, exc)
        return self._local.search(query, limit=limit)

    def search_accessible(self, query: str, user_id: str = "", space_id: str = "", limit: int = 20) -> list[KnowledgeEntry]:
        if self._remote is not None and hasattr(self._remote, "search_accessible"):
            try:
                results = self._remote.search_accessible(query, user_id=user_id, limit=limit)
                if results:
                    return results
            except Exception as exc:
                logger.warning("Remote accessible search failed for %r/%s: %s", query, user_id, exc)
        return self._local.search_accessible(query, user_id=user_id, space_id=space_id, limit=limit)

    def list_for_owner(self, owner_type: KnowledgeOwnerType, owner_id: str) -> list[KnowledgeEntry]:
        if self._remote is not None and hasattr(self._remote, "list_for_owner"):
            try:
                results = self._remote.list_for_owner(owner_type, owner_id)
                if results:
                    return results
            except Exception as exc:
                logger.warning("Remote list_for_owner failed for %s/%s: %s", owner_type.value, owner_id, exc)
        return self._local.list_for_owner(owner_type, owner_id)

    def list_accessible(self, user_id: str = "", limit: int = 50) -> list[KnowledgeEntry]:
        if self._remote is not None and hasattr(self._remote, "list_accessible"):
            try:
                results = self._remote.list_accessible(user_id=user_id)
                if results:
                    return results[:limit]
            except Exception as exc:
                logger.warning("Remote list_accessible failed for %s: %s", user_id, exc)
        return self._local.list_accessible(user_id=user_id, limit=limit)

    def delete(self, entry_id: str, user_id: str = "") -> bool:
        remote_deleted = False
        if self._remote is not None and hasattr(self._remote, "delete"):
            try:
                remote_deleted = bool(self._remote.delete(entry_id, user_id=user_id))
            except Exception as exc:
                logger.warning("Remote knowledge delete failed for %s: %s", entry_id, exc)
        local_deleted = bool(self._local.delete(entry_id, user_id=user_id))
        return remote_deleted or local_deleted

    def stats(self) -> dict[str, Any]:
        return self._local.stats()


def build_knowledge_repository() -> UnifiedKnowledgeRepository:
    local_repo = FtsKnowledgeRepository(Database.get().connect())
    remote_repo = None
    try:
        from src.knowledge.gbrain_repo import GbrainKnowledgeRepository

        remote_repo = GbrainKnowledgeRepository()
    except Exception as exc:
        logger.warning("Gbrain repository unavailable, using local knowledge only: %s", exc)
    return UnifiedKnowledgeRepository(local_repo=local_repo, remote_repo=remote_repo)
