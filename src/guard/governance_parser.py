from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class GovernanceCommand:
    kind: str
    raw_text: str


class GovernanceParser:
    """Detect a minimal set of governance commands from chat text."""

    def parse(self, text: str) -> GovernanceCommand | None:
        normalized = text.strip()
        lowered = normalized.lower()
        if "暂停" in normalized or "pause" in lowered:
            return GovernanceCommand(kind="pause", raw_text=text)
        if "这不是任务" in normalized or "not a task" in lowered:
            return GovernanceCommand(kind="not_a_task", raw_text=text)
        if "转人工" in normalized or "handoff" in lowered:
            return GovernanceCommand(kind="handoff_to_human", raw_text=text)
        return None
