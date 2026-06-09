from __future__ import annotations

import json

from src.models.contracts import Task as TaskModel
from src.models.task_repository import TaskRepository as TaskRepositoryProtocol
from src.store.task_repo import TaskRepository as SqliteTaskRepo


class SqliteTaskRepositoryAdapter:
    """Adapts SQLite store.task_repo.TaskRepository to the models protocol."""

    def __init__(self, repo: SqliteTaskRepo) -> None:
        self._repo = repo

    def save(self, task: TaskModel) -> TaskModel:
        self._repo._conn.execute(
            """INSERT OR REPLACE INTO tasks
               (id, title, description, project_id, assignee_user_id, collaborator_ids,
                source_message_ids, status, due_at, blocked_reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                task.id,
                task.title,
                task.description,
                task.project_id,
                task.assignee_user_id,
                json.dumps(task.collaborator_ids, ensure_ascii=False),
                json.dumps(task.source_message_ids, ensure_ascii=False),
                task.status.value,
                task.due_at.isoformat() if task.due_at else None,
                task.blocked_reason,
            ),
        )
        self._repo._conn.commit()
        return task

    def get(self, task_id: str) -> TaskModel | None:
        tasks = self._repo.list_tasks(project_id="")
        for t in tasks:
            if t.id == task_id:
                return t
        return None

    def list_by_project(self, project_id: str) -> list[TaskModel]:
        return self._repo.list_tasks(project_id=project_id)
