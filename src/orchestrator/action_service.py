from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.gateway.card_renderer import render_task_draft_card
from src.models import OrchestratorAction
from src.orchestrator.task_service import TaskService


@dataclass(slots=True)
class ActionOutcome:
    kind: str
    metadata: dict[str, Any]


class OrchestratorActionService:
    """Apply orchestrator actions into the minimal task lifecycle.

    M1 only needs one real action path:
    - task_draft_identified -> create draft task

    Governance commands are surfaced but not executed deeply yet; they are
    recorded as action outcomes for the next layer to consume.
    """

    def __init__(self, task_service: TaskService) -> None:
        self.task_service = task_service

    def apply(self, action: OrchestratorAction) -> ActionOutcome:
        if action.kind == "task_draft_identified":
            draft = action.payload["draft"]
            task_id = action.payload.get("task_id") or f"draft-{draft.source_message_ids[0]}"
            task = self.task_service.create_from_draft(draft, task_id=task_id)
            card = render_task_draft_card(task)
            return ActionOutcome(
                kind="draft_task_created",
                metadata={"task_id": task.id, "project_id": task.project_id, "card": card},
            )

        if action.kind == "governance_command_detected":
            command = action.payload["command"]
            return ActionOutcome(
                kind="governance_command_buffered",
                metadata={"command_kind": command.kind, "message_id": action.payload.get("message_id")},
            )

        raise ValueError(f"unsupported action kind: {action.kind}")
