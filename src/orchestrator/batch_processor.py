from __future__ import annotations

from collections import defaultdict

from src.models.contracts import Message


class BatchProcessor:
    """Simple in-memory batch buffer for M1."""

    def __init__(self) -> None:
        self._messages_by_space: dict[str, list[Message]] = defaultdict(list)
        self._seen_ids: set[str] = set()

    def submit(self, message: Message) -> None:
        if message.id in self._seen_ids:
            return
        self._seen_ids.add(message.id)
        self._messages_by_space[message.space_id].append(message)

    def drain(self, space_id: str) -> list[Message]:
        messages = self._messages_by_space.get(space_id, [])
        self._messages_by_space[space_id] = []
        return messages

    def space_ids(self) -> list[str]:
        return list(self._messages_by_space.keys())
