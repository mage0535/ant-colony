from __future__ import annotations

from src.models.contracts import GuardContext, GuardDecision, GuardDecisionType, OrchestratorAction


class ActionGuard:
    """Minimal governance guard for M1."""

    def evaluate(self, action: OrchestratorAction, context: GuardContext) -> GuardDecision:
        if action.kind == "governance_command_detected":
            return GuardDecision(
                decision=GuardDecisionType.ALLOW,
                reason="治理命令允许优先进入控制链路处理。",
            )

        if action.kind == "task_draft_identified":
            return GuardDecision(
                decision=GuardDecisionType.REQUIRE_CONFIRMATION,
                reason="任务草案需要相关人轻确认后才能入板。",
            )

        return GuardDecision(
            decision=GuardDecisionType.ALLOW,
            reason="当前动作无需额外治理拦截。",
        )
