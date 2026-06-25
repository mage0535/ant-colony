from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.models.contracts import Message, MessageContext, SpaceType


@dataclass(slots=True)
class AdaptedInboundMessage:
    message: Message
    context: MessageContext


def adapt_wecom_payload(payload: dict[str, Any]) -> AdaptedInboundMessage:
    """Map a minimal inbound WeCom-like payload into internal contracts.

    This adapter is intentionally permissive for M1/P-1:
    - it supports a minimal subset of fields
    - it does not validate signatures or encryption
    - it prefers stable internal structure over provider-specific detail

    Expected payload examples can evolve during P-1 as real WeCom message
    samples become available.
    """

    sender_user_id = _pick(payload, "from", "from_user_id", "sender_user_id", default="unknown-user")
    text = _pick(payload, "text", "content", default="")
    msg_id = _pick(payload, "msg_id", "message_id", default=_fallback_message_id(sender_user_id, text))
    created_at = _parse_timestamp(_pick(payload, "created_at", "timestamp"))

    project_id = _pick(payload, "project_id")
    dept_id = _pick(payload, "dept_id")
    explicit_space_id = _pick(payload, "space_id")
    has_space_ref = any(k in payload for k in ("space_id", "project_id", "dept_id"))
    is_direct = bool(_pick(payload, "is_direct", default=not has_space_ref))
    space_id = _pick(payload, "space_id", default=project_id or dept_id or "default-space")

    if project_id:
        space_type = SpaceType.PROJECT
    else:
        space_type = SpaceType.DEPARTMENT

    provider = _pick(payload, "provider", "platform", default="wecom")
    transport = _pick(payload, "transport", default="")

    message = Message(
        id=msg_id,
        space_id=space_id,
        sender_user_id=sender_user_id,
        content=text,
        msg_type=_pick(payload, "msg_type", default="text"),
        created_at=created_at,
        metadata={
            "provider": provider,
            "transport": transport,
            "is_direct": is_direct,
            "raw": payload,
        },
    )

    context = MessageContext(
        space_type=space_type,
        space_id=space_id,
        dept_id=dept_id,
        project_id=project_id,
        mentions=list(_pick(payload, "mentions", default=[])),
        metadata={
            "provider": provider,
            "transport": transport,
            "conversation_type": _pick(payload, "conversation_type"),
            "is_direct": is_direct,
        },
    )

    return AdaptedInboundMessage(message=message, context=context)


def _pick(payload: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return default


def _fallback_message_id(sender_user_id: str, text: str) -> str:
    return f"fallback-{sender_user_id}-{abs(hash(text))}"


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value)
    return None
