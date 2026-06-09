from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.models.contracts import Message


class RouteKind(str, Enum):
    PERSONAL = "personal"
    SPACE_BATCH = "space_batch"


@dataclass(slots=True)
class RouteDecision:
    kind: RouteKind
    target_id: str


class Dispatcher:
    """Minimal routing logic for M1.

    M1 keeps routing intentionally simple:
    - messages marked as direct go to a personal agent
    - everything else is treated as a space message for batch analysis
    """

    def route(self, message: Message) -> RouteDecision:
        is_direct = bool(message.metadata.get("is_direct"))
        if is_direct:
            return RouteDecision(kind=RouteKind.PERSONAL, target_id=message.sender_user_id)
        return RouteDecision(kind=RouteKind.SPACE_BATCH, target_id=message.space_id)
