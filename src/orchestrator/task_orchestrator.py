from __future__ import annotations

from src.guard import GovernanceParser
from src.agents.project_agent import ProjectAgent
from src.models.contracts import Message, OrchestratorAction


class TaskOrchestrator:
    """Translate batches of chat messages into structured actions."""

    def __init__(self, project_agent: ProjectAgent, governance_parser: GovernanceParser | None = None) -> None:
        self.project_agent = project_agent
        self.governance_parser = governance_parser or GovernanceParser()

    def on_batch(self, project_id: str, messages: list[Message]) -> list[OrchestratorAction]:
        actions: list[OrchestratorAction] = []

        # Governance commands should be surfaced before task generation.
        for message in messages:
            command = self.governance_parser.parse(message.content)
            if command is not None:
                actions.append(
                    OrchestratorAction(
                        kind="governance_command_detected",
                        space_id=project_id,
                        payload={"command": command, "message_id": message.id},
                    )
                )

        drafts = self.project_agent.identify_tasks(project_id, messages)
        seen_titles: set[str] = set()
        for draft in drafts:
            normalized_title = draft.title.strip().lower()
            if normalized_title in seen_titles:
                continue
            seen_titles.add(normalized_title)
            actions.append(
                OrchestratorAction(
                    kind="task_draft_identified",
                    space_id=project_id,
                    payload={"draft": draft},
                )
            )
        return actions
