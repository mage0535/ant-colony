from __future__ import annotations

from typing import Any

from src.gateway.card_actions import parse_task_card_action
from src.orchestrator.confirmation_service import ConfirmationOutcome, TaskConfirmationService


class CardCallbackService:
    """Map provider callback payloads into internal confirmation actions."""

    def __init__(self, confirmation_service: TaskConfirmationService) -> None:
        self.confirmation_service = confirmation_service

    def handle_task_card_callback(self, payload: dict[str, Any]) -> ConfirmationOutcome:
        action = parse_task_card_action(payload)
        return self.confirmation_service.apply(action)
