from __future__ import annotations

from typing import Protocol

from src.models.contracts import Task


class TaskRepository(Protocol):
    def save(self, task: Task) -> Task:
        ...

    def get(self, task_id: str) -> Task | None:
        ...

    def list_by_project(self, project_id: str) -> list[Task]:
        ...


class InMemoryTaskRepository:
    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}

    def save(self, task: Task) -> Task:
        self._tasks[task.id] = task
        return task

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def list_by_project(self, project_id: str) -> list[Task]:
        return [task for task in self._tasks.values() if task.project_id == project_id]
