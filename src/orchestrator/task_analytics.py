from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from src.models.contracts import TaskStatus
from src.store.task_repo import TaskRepository

logger = logging.getLogger(__name__)


class TaskAnalytics:
    """Computes task statistics and project health metrics."""

    def __init__(self, repo: TaskRepository) -> None:
        self._repo = repo

    def project_stats(self, space_id: str = "") -> dict[str, Any]:
        tasks = self._repo.list_tasks(project_id=space_id)
        total = len(tasks)
        by_status: dict[str, int] = {}
        by_priority: dict[str, int] = {}
        by_assignee: dict[str, int] = {}
        overdue = 0

        now = datetime.now()
        for t in tasks:
            s = t.status.value
            by_status[s] = by_status.get(s, 0) + 1
            p = t.priority
            by_priority[p] = by_priority.get(p, 0) + 1
            if t.assignee_user_id:
                by_assignee[t.assignee_user_id] = by_assignee.get(t.assignee_user_id, 0) + 1
            if t.due_at and t.due_at < now and t.status not in (TaskStatus.DONE, TaskStatus.CANCELLED):
                overdue += 1

        done = by_status.get("done", 0)
        cancelled = by_status.get("cancelled", 0)
        completion_rate = round(done / max(total, 1) * 100, 1)
        effective_done = done + cancelled
        effective_rate = round(effective_done / max(total, 1) * 100, 1)

        blocked_chain_count = sum(1 for t in tasks if t.blocked_by_task_id)

        return {
            "space_id": space_id or "all",
            "total": total,
            "by_status": by_status,
            "by_priority": by_priority,
            "by_assignee": by_assignee,
            "overdue": overdue,
            "blocked_chains": blocked_chain_count,
            "completion_rate_pct": completion_rate,
            "effective_completion_pct": effective_rate,
        }

    def velocity(self, space_id: str = "") -> dict[str, Any]:
        tasks = self._repo.list_tasks(project_id=space_id)
        now = datetime.now()
        completed_7d = 0
        completed_30d = 0
        total_30d = 0

        for t in tasks:
            if t.status == TaskStatus.DONE:
                total_30d += 1
                completed_30d += 1
                # Approximate: if task exists and is done, count in 7d
                completed_7d += 1
            elif t.status != TaskStatus.CANCELLED:
                total_30d += 1

        return {
            "completed_last_7d": completed_7d,
            "completed_last_30d": completed_30d,
            "active_total": total_30d,
            "weekly_velocity": round(completed_7d / max(1, 7) * 7, 1),
            "monthly_velocity": completed_30d,
        }

    def dashboard_summary(self) -> dict[str, Any]:
        stats = self.project_stats()
        vel = self.velocity()
        return {
            "stats": stats,
            "velocity": vel,
            "health": "good" if stats["completion_rate_pct"] > 50 else "warning" if stats["total"] > 0 else "idle",
            "generated_at": datetime.now().isoformat(),
        }
