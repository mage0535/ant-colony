from __future__ import annotations

from src.gateway.outbound import OutboundMessage
from src.models import Reminder, Task


class NotificationService:
    """Translate internal task/reminder objects into outbound messages."""

    def build_task_draft_notification(self, task: Task, card_payload: dict, target_space_id: str) -> OutboundMessage:
        return OutboundMessage(
            target_id=target_space_id,
            target_type="space",
            content_type="card",
            body=card_payload,
            metadata={"task_id": task.id, "message_kind": "task_draft_confirmation"},
        )

    def build_reminder_notification(self, reminder: Reminder, target_user_id: str) -> OutboundMessage:
        return OutboundMessage(
            target_id=target_user_id,
            target_type="user",
            content_type="text",
            body={"text": reminder.text},
            metadata={"task_id": reminder.task_id, "message_kind": "task_reminder"},
        )
