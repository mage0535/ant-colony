from __future__ import annotations

from dataclasses import replace

from src.models.contracts import BlockedTask, Task, TaskDraft, TaskStatus


def materialize_draft(draft: TaskDraft, task_id: str) -> Task:
    return Task(
        id=task_id,
        title=draft.title,
        description=draft.description,
        project_id=draft.project_id,
        status=TaskStatus.DRAFT,
        assignee_user_id=draft.assignee_user_id,
        collaborator_ids=list(draft.collaborator_ids),
        source_message_ids=list(draft.source_message_ids),
        due_at=draft.due_at,
        metadata={"confidence": draft.confidence, **draft.metadata},
    )


def confirm_task(task: Task) -> Task:
    if task.status != TaskStatus.DRAFT:
        raise ValueError("only draft tasks can be confirmed")
    return replace(task, status=TaskStatus.CONFIRMED)


def start_task(task: Task) -> Task:
    if task.status not in {TaskStatus.CONFIRMED, TaskStatus.BLOCKED}:
        raise ValueError("task must be confirmed or blocked before starting")
    return replace(task, status=TaskStatus.IN_PROGRESS, blocked_reason=None)


def block_task(task: Task, reason: str) -> tuple[Task, BlockedTask]:
    if task.status not in {TaskStatus.CONFIRMED, TaskStatus.IN_PROGRESS}:
        raise ValueError("task must be confirmed or in progress before blocking")
    blocked = replace(task, status=TaskStatus.BLOCKED, blocked_reason=reason)
    signal = BlockedTask(
        task_id=task.id,
        project_id=task.project_id,
        reason=reason,
        suggested_next_steps=["确认阻塞原因", "指定下一步负责人"],
    )
    return blocked, signal


def complete_task(task: Task) -> Task:
    if task.status not in {TaskStatus.CONFIRMED, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED}:
        raise ValueError("task must be active before completion")
    return replace(task, status=TaskStatus.DONE)
