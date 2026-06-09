from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class SpaceType(str, Enum):
    DEPARTMENT = "department"
    PROJECT = "project"


class TaskStatus(str, Enum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"
    CANCELLED = "cancelled"


class GuardDecisionType(str, Enum):
    ALLOW = "allow"
    REQUIRE_CONFIRMATION = "require_confirmation"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


@dataclass(slots=True)
class Message:
    id: str
    space_id: str
    sender_user_id: str
    content: str
    msg_type: str = "text"
    created_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MessageContext:
    space_type: SpaceType
    space_id: str
    dept_id: str | None = None
    project_id: str | None = None
    mentions: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentResponse:
    text: str
    visible_to_user: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TaskDraft:
    title: str
    description: str
    project_id: str
    source_message_ids: list[str]
    assignee_user_id: str | None = None
    collaborator_ids: list[str] = field(default_factory=list)
    due_at: datetime | None = None
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Task:
    id: str
    title: str
    description: str
    project_id: str
    status: TaskStatus = TaskStatus.DRAFT
    assignee_user_id: str | None = None
    collaborator_ids: list[str] = field(default_factory=list)
    source_message_ids: list[str] = field(default_factory=list)
    due_at: datetime | None = None
    blocked_reason: str | None = None
    blocked_by_task_id: str | None = None
    priority: str = "medium"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BlockedTask:
    task_id: str
    project_id: str
    reason: str
    suggested_next_steps: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Reminder:
    task_id: str
    reason: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OrchestratorAction:
    kind: str
    space_id: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GuardContext:
    actor_user_id: str | None
    actor_role: str | None
    space_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GuardDecision:
    decision: GuardDecisionType
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)
