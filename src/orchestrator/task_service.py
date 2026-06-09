from __future__ import annotations

from src.models.contracts import BlockedTask, Task, TaskDraft
from src.models.task_flow import block_task, complete_task, confirm_task, materialize_draft, start_task
from src.models.task_repository import TaskRepository


class TaskService:
    """Minimal task lifecycle service for M1.

    Uses an abstract repository so later phases can swap in SQLAlchemy-backed
    persistence without changing the call contract.
    """

    def __init__(self, repository: TaskRepository) -> None:
        self.repository = repository

    def create_from_draft(self, draft: TaskDraft, task_id: str) -> Task:
        task = materialize_draft(draft, task_id)
        return self.repository.save(task)

    def confirm(self, task_id: str) -> Task:
        task = self._require(task_id)
        confirmed = confirm_task(task)
        return self.repository.save(confirmed)

    def start(self, task_id: str) -> Task:
        task = self._require(task_id)
        started = start_task(task)
        return self.repository.save(started)

    def block(self, task_id: str, reason: str) -> tuple[Task, BlockedTask]:
        task = self._require(task_id)
        blocked_task, signal = block_task(task, reason)
        self.repository.save(blocked_task)
        return blocked_task, signal

    def complete(self, task_id: str) -> Task:
        task = self._require(task_id)
        completed = complete_task(task)
        return self.repository.save(completed)

    def _require(self, task_id: str) -> Task:
        task = self.repository.get(task_id)
        if task is None:
            raise KeyError(f"task not found: {task_id}")
        return task
