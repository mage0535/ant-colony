from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.store.task_repo import TaskRepository

logger = logging.getLogger(__name__)


@dataclass
class WorkEntry:
    user_id: str
    task_id: str
    title: str
    status: str
    updated_at: str


class WorkJournal:
    """Per-user work journal — tracks assigned tasks and their status timeline.

    Queries TaskRepository for tasks assigned to a user, returns structured
    journal entries sorted by recency.
    """

    def __init__(self, repo: TaskRepository) -> None:
        self._repo = repo

    def get_user_journal(self, user_id: str) -> list[dict[str, Any]]:
        all_tasks = self._repo.list_tasks()
        entries: list[dict[str, Any]] = []
        for t in all_tasks:
            if t.assignee_user_id == user_id:
                entries.append({
                    "task_id": t.id,
                    "title": t.title,
                    "status": t.status.value,
                    "project_id": t.project_id,
                    "blocked_reason": t.blocked_reason,
                    "blocked_by": t.blocked_by_task_id,
                    "due_at": t.due_at.isoformat() if t.due_at else None,
                })
        return sorted(entries, key=lambda e: e["task_id"], reverse=True)

    def get_summary(self, user_id: str) -> dict[str, Any]:
        entries = self.get_user_journal(user_id)
        by_status: dict[str, int] = {}
        for e in entries:
            s = e["status"]
            by_status[s] = by_status.get(s, 0) + 1
        return {
            "user_id": user_id,
            "total_tasks": len(entries),
            "by_status": by_status,
            "recent": entries[:10],
        }
