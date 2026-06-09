from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class TaskCardAction:
    action_id: str
    task_id: str
    actor_user_id: str
    metadata: dict[str, Any]


def parse_task_card_action(payload: dict[str, Any]) -> TaskCardAction:
    return TaskCardAction(
        action_id=str(payload["action_id"]),
        task_id=str(payload["task_id"]),
        actor_user_id=str(payload["actor_user_id"]),
        metadata=dict(payload.get("metadata", {})),
    )
