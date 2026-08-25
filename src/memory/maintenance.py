from __future__ import annotations

import logging
import sqlite3
import time
from typing import Any

from src.store.task_repo import TaskRepository

logger = logging.getLogger(__name__)


class MemoryMaintenanceCycle:
    """Session archiver + memory lifecycle — replaces original maintenance_cycle.py.

    Runs on-demand to: archive messages → extract facts → build knowledge graph.
    Uses SQLite-backed Warm + Cold stores instead of PostgreSQL Hindsight/gbrain.
    """

    def __init__(self, repo: TaskRepository, warm_store: Any, cold_store: Any) -> None:
        self._repo = repo
        self.warm = warm_store
        self.cold = cold_store

    def archive_session(self, space_id: str, batch_size: int = 50) -> dict[str, Any]:
        try:
            messages = self._repo.list_messages(space_id=space_id, limit=batch_size)
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower():
                logger.warning("MemoryMaintenance: database busy while listing messages for %s: %s", space_id, exc)
                return {"space_id": space_id, "messages_archived": 0, "facts_retained": 0, "relations_extracted": 0, "skipped": "database_busy"}
            raise
        if not messages:
            return {"space_id": space_id, "messages_archived": 0, "facts_retained": 0, "relations_extracted": 0}

        warm_count = 0
        cold_count = 0
        try:
            for m in messages:
                content = str(m.get("content", ""))
                if len(content) < 20:
                    continue
                self.warm.retain(content, source=f"space:{space_id}", domain=space_id)
                warm_count += 1
                cold_count += self.cold.extract_and_ingest(content, domain=space_id)

            # Mark as processed
            self._repo.mark_messages_processed(space_id)
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower():
                logger.warning("MemoryMaintenance: database busy while archiving %s: %s", space_id, exc)
                return {
                    "space_id": space_id,
                    "messages_archived": 0,
                    "facts_retained": warm_count,
                    "relations_extracted": cold_count,
                    "skipped": "database_busy",
                }
            raise

        logger.info("MemoryMaintenance: archived %d msgs → %d facts, %d edges (space=%s)",
                     len(messages), warm_count, cold_count, space_id)
        return {
            "space_id": space_id,
            "messages_archived": len(messages),
            "facts_retained": warm_count,
            "relations_extracted": cold_count,
        }

    def run_cycle(self, space_id: str = "") -> dict[str, Any]:
        start = time.time()
        results = []
        if space_id:
            results.append(self.archive_session(space_id))
        else:
            all_tasks = self._repo.list_tasks()
            space_ids = list({t.project_id for t in all_tasks})
            for sid in space_ids:
                results.append(self.archive_session(sid))
        total_msgs = sum(r["messages_archived"] for r in results)
        total_facts = sum(r["facts_retained"] for r in results)
        total_edges = sum(r["relations_extracted"] for r in results)
        logger.info("MemoryMaintenance cycle complete: %d msgs → %d facts + %d edges in %.1fs",
                     total_msgs, total_facts, total_edges, time.time() - start)
        return {
            "spaces_processed": len(results),
            "total_messages": total_msgs,
            "total_facts": total_facts,
            "total_relations": total_edges,
            "duration_seconds": round(time.time() - start, 2),
        }
