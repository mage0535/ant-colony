from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

_sse_queues: list[asyncio.Queue] = []


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _sse_queues.append(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    if q in _sse_queues:
        _sse_queues.remove(q)


def emit(event_type: str, **kwargs: Any) -> None:
    payload: dict[str, Any] = {"type": event_type, **kwargs}
    dead: list[asyncio.Queue] = []
    for q in _sse_queues:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        if q in _sse_queues:
            _sse_queues.remove(q)
    logger.debug("SSE emit: %s %s", event_type, kwargs)
