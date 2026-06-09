from __future__ import annotations

from dataclasses import dataclass, field

from src.gateway.outbound import OutboundMessage
from src.guard import ActionGuard
from src.models import GuardContext, Message
from src.models.contracts import GuardDecisionType
from src.orchestrator.action_service import ActionOutcome, OrchestratorActionService
from src.orchestrator.notification_service import NotificationService
from src.orchestrator.task_orchestrator import TaskOrchestrator


@dataclass(slots=True)
class BatchExecutionResult:
    actions_seen: int = 0
    outcomes: list[ActionOutcome] = field(default_factory=list)
    outbound_messages: list[OutboundMessage] = field(default_factory=list)


class BatchExecutionService:
    """Run the minimal batch pipeline end-to-end."""

    def __init__(
        self,
        orchestrator: TaskOrchestrator,
        action_guard: ActionGuard,
        action_service: OrchestratorActionService,
        notification_service: NotificationService,
    ) -> None:
        self.orchestrator = orchestrator
        self.action_guard = action_guard
        self.action_service = action_service
        self.notification_service = notification_service

    def process_batch(self, project_id: str, messages: list[Message]) -> BatchExecutionResult:
        actions = self.orchestrator.on_batch(project_id, messages)
        result = BatchExecutionResult(actions_seen=len(actions))

        for action in actions:
            decision = self.action_guard.evaluate(
                action,
                GuardContext(actor_user_id=None, actor_role=None, space_id=project_id),
            )
            if decision.decision == GuardDecisionType.DENY:
                continue

            outcome = self.action_service.apply(action)
            result.outcomes.append(outcome)

            if outcome.kind == "draft_task_created":
                task = self.action_service.task_service.repository.get(outcome.metadata["task_id"])
                if task is not None:
                    outbound = self.notification_service.build_task_draft_notification(
                        task=task,
                        card_payload=outcome.metadata["card"],
                        target_space_id=project_id,
                    )
                    result.outbound_messages.append(outbound)

        return result
