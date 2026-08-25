from __future__ import annotations

import os


DEFAULT_SOFT_LIMIT = int(os.environ.get("ANT_COLONY_IM_REPLY_CHARS", "1200"))


def split_text_for_im(
    text: str,
    *,
    hard_limit: int,
    soft_limit: int | None = None,
) -> list[str]:
    normalized = str(text or "").replace("\r\n", "\n").strip()
    if not normalized:
        return []
    effective_limit = min(hard_limit, soft_limit or DEFAULT_SOFT_LIMIT)
    if len(normalized) <= effective_limit and _utf8_len(normalized) <= hard_limit:
        return [normalized]

    body_char_limit = max(80, effective_limit - 20)
    body_byte_limit = max(200, hard_limit - 80)
    raw_chunks = _split_greedily(normalized, body_char_limit, body_byte_limit)
    if len(raw_chunks) == 1:
        return raw_chunks

    total = len(raw_chunks)
    chunks: list[str] = []
    for index, chunk in enumerate(raw_chunks, start=1):
        prefix = f"\uff08{index}/{total}\uff09\n"
        available_bytes = max(100, hard_limit - _utf8_len(prefix))
        if _utf8_len(chunk) <= available_bytes:
            chunks.append(f"{prefix}{chunk}")
        else:
            for nested in _split_greedily(chunk, body_char_limit, available_bytes):
                chunks.append(f"{prefix}{nested}")
    return chunks


def _split_greedily(text: str, char_limit: int, byte_limit: int) -> list[str]:
    remaining = text.strip()
    chunks: list[str] = []
    while remaining:
        if len(remaining) <= char_limit and _utf8_len(remaining) <= byte_limit:
            chunks.append(remaining)
            break
        cut = _find_cut_point(remaining, char_limit, byte_limit)
        chunk = remaining[:cut].rstrip()
        if not chunk:
            cut = _max_chars_within_bytes(remaining, byte_limit)
            chunk = remaining[:cut]
        chunks.append(chunk)
        remaining = remaining[cut:].lstrip()
    return chunks


def _find_cut_point(text: str, char_limit: int, byte_limit: int) -> int:
    limit = min(char_limit, _max_chars_within_bytes(text, byte_limit))
    candidates = ("\n\n", "\n", "\u3002", "\uff01", "\uff1f", "\uff1b", ".", "!", "?", ";", "\uff0c", ",", " ")
    minimum = max(1, limit // 2)
    for token in candidates:
        pos = text.rfind(token, 0, limit + 1)
        if pos >= minimum:
            return pos + len(token)
    return limit


def _utf8_len(text: str) -> int:
    return len(str(text or "").encode("utf-8"))


def _max_chars_within_bytes(text: str, byte_limit: int) -> int:
    used = 0
    for index, char in enumerate(text):
        used += _utf8_len(char)
        if used > byte_limit:
            return max(1, index)
    return len(text)
