from __future__ import annotations

from typing import Any

from src.models import Task, TaskStatus


def render_task_draft_card(task: Task) -> dict[str, Any]:
    """Render a minimal provider-agnostic confirmation card payload.

    M1 keeps the structure provider-agnostic so the real WeCom/Feishu card
    adapter can be added later without changing upstream task flow.
    """

    if task.status != TaskStatus.DRAFT:
        raise ValueError("only draft tasks can be rendered as confirmation cards")

    return {
        "card_type": "task_draft_confirmation",
        "task_id": task.id,
        "title": task.title,
        "description": task.description,
        "assignee_user_id": task.assignee_user_id,
        "actions": [
            {"id": "confirm_task", "label": "确认入板"},
            {"id": "reject_task", "label": "这不是任务"},
            {"id": "handoff_to_human", "label": "转人工确认"},
        ],
        "metadata": {
            "project_id": task.project_id,
            "source_message_ids": list(task.source_message_ids),
        },
    }
