from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(slots=True)
class OutboundMessage:
    target_id: str
    target_type: str  # user | space
    content_type: str  # text | card
    body: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)


class OutboundNotifier(Protocol):
    def send(self, message: OutboundMessage) -> None:
        ...


class InMemoryOutboundNotifier:
    def __init__(self) -> None:
        self.sent_messages: list[OutboundMessage] = []

    def send(self, message: OutboundMessage) -> None:
        self.sent_messages.append(message)
