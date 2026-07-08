from __future__ import annotations

from src.gateway.wecom_file_handler import summarize_file_bytes


def summarize_platform_file_bytes(
    *,
    platform: str,
    user_id: str,
    chat_id: str,
    chat_type: str,
    data: bytes,
    filename: str,
) -> str:
    owner_type, owner_id = _infer_owner(chat_id=chat_id, chat_type=chat_type, user_id=user_id)
    return summarize_file_bytes(
        data,
        filename,
        from_user_id=user_id,
        owner_type=owner_type,
        owner_id=owner_id,
    )


def _infer_owner(*, chat_id: str, chat_type: str, user_id: str) -> tuple[str, str]:
    normalized = str(chat_type or "").lower()
    if normalized in {"p2p", "single", "direct"}:
        return "personal", user_id
    if chat_id:
        return "project", chat_id
    return "personal", user_id
