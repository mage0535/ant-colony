from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from src.store.task_repo import TaskRepository
from src.models.contracts import TaskStatus
from src.web.sse_bus import emit

logger = logging.getLogger(__name__)


class DeadlineTracker:
    """Tracks task deadlines and auto-generates reminders for overdue/incoming items.

    Integrates with TaskRepository to scan due dates and emit reminders.
    """

    def __init__(self, repo: TaskRepository) -> None:
        self._repo = repo

    def set_deadline(self, task_id: str, due_at: str) -> bool:
        self._repo._conn.execute(
            "UPDATE tasks SET due_at = ? WHERE id = ?", (due_at, task_id)
        )
        self._repo._conn.commit()
        emit("deadline_set", task_id=task_id, due_at=due_at)
        return True

    def check_and_remind(self, space_id: str = "") -> list[dict[str, Any]]:
        tasks = self._repo.list_tasks(project_id=space_id)
        now = datetime.now()
        reminders: list[dict[str, Any]] = []
        for t in tasks:
            if t.status in (TaskStatus.DONE, TaskStatus.CANCELLED):
                continue
            if not t.due_at:
                continue
            hours_left = (t.due_at - now).total_seconds() / 3600
            if hours_left < 0 and t.status != TaskStatus.BLOCKED:
                text = f"⏰ 逾期: {t.title} (已超 {abs(int(hours_left))} 小时)"
                rid = self._repo.save_reminder(t.id, t.project_id, "overdue", text)
                reminders.append({"task_id": t.id, "hours_overdue": abs(int(hours_left)), "reminder_id": rid})
                logger.info("DeadlineTracker: overdue %s (%sh)", t.id, abs(int(hours_left)))
            elif 0 < hours_left < 24:
                text = f"⏳ 即将到期: {t.title} (剩余 {int(hours_left)} 小时)"
                rid = self._repo.save_reminder(t.id, t.project_id, "approaching", text)
                reminders.append({"task_id": t.id, "hours_remaining": int(hours_left), "reminder_id": rid})
                logger.info("DeadlineTracker: approaching %s (%sh)", t.id, int(hours_left))
        return reminders
