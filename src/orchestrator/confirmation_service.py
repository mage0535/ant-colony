from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.gateway.card_actions import TaskCardAction
from src.models.task_repository import TaskRepository
from src.orchestrator.task_service import TaskService


@dataclass(slots=True)
class ConfirmationOutcome:
    kind: str
    metadata: dict[str, Any]


class TaskConfirmationService:
    """Minimal confirmation action handler for M1."""

    def __init__(self, task_service: TaskService, repository: TaskRepository) -> None:
        self.task_service = task_service
        self.repository = repository

    def apply(self, action: TaskCardAction) -> ConfirmationOutcome:
        if action.action_id == "confirm_task":
            task = self.task_service.confirm(action.task_id)
            return ConfirmationOutcome(
                kind="task_confirmed",
                metadata={"task_id": task.id, "status": task.status.value, "actor_user_id": action.actor_user_id},
            )

        if action.action_id == "reject_task":
            task = self.repository.get(action.task_id)
            if task is None:
                raise KeyError(f"task not found: {action.task_id}")
            task.metadata["rejected"] = True
            task.metadata["rejected_by"] = action.actor_user_id
            self.repository.save(task)
            return ConfirmationOutcome(
                kind="task_rejected",
                metadata={"task_id": task.id, "status": task.status.value, "actor_user_id": action.actor_user_id},
            )

        if action.action_id == "handoff_to_human":
            task = self.repository.get(action.task_id)
            if task is None:
                raise KeyError(f"task not found: {action.task_id}")
            task.metadata["handoff_to_human"] = True
            self.repository.save(task)
            return ConfirmationOutcome(
                kind="task_handoff_requested",
                metadata={"task_id": task.id, "status": task.status.value, "actor_user_id": action.actor_user_id},
            )

        raise ValueError(f"unsupported card action: {action.action_id}")
