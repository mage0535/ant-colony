from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

from fastapi import HTTPException, Request


DEFAULT_ADMIN_SESSION_TTL_SECONDS = 3600


def create_admin_console_token(
    *,
    platform: str,
    user_id: str,
    ttl_seconds: int = DEFAULT_ADMIN_SESSION_TTL_SECONDS,
    now: float | None = None,
) -> str:
    secret = _admin_secret()
    if not secret:
        raise RuntimeError("ANT_COLONY_ADMIN_SESSION_SECRET or ANT_COLONY_AUTH_TOKEN is required")
    issued_at = int(time.time() if now is None else now)
    payload = {
        "platform": _normalize_platform(platform),
        "user_id": user_id.strip(),
        "exp": issued_at + int(ttl_seconds),
    }
    body = _b64(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    sig = _sign(body, secret)
    return f"{body}.{sig}"


def require_admin_context(
    *,
    platform: str,
    user_id: str,
    admin_token: str,
    now: float | None = None,
) -> dict[str, Any]:
    normalized_platform = _normalize_platform(platform)
    normalized_user_id = user_id.strip()
    if not normalized_user_id:
        raise HTTPException(401, "缺少企业 IM 用户身份")
    if not _verify_admin_console_token(
        platform=normalized_platform,
        user_id=normalized_user_id,
        token=admin_token,
        now=now,
    ):
        raise HTTPException(401, "管理员访问令牌无效或已过期")
    if not is_platform_admin(normalized_platform, normalized_user_id):
        raise HTTPException(403, "当前企业 IM 用户不是平台管理员")
    return {"platform": normalized_platform, "user_id": normalized_user_id, "role": "admin"}


def require_admin_context_from_request(request: Request) -> dict[str, Any]:
    platform = (
        request.query_params.get("platform")
        or request.headers.get("X-Platform")
        or "wecom"
    )
    user_id = (
        request.query_params.get("user_id")
        or request.headers.get("X-User-ID")
        or request.headers.get("X-IM-User-ID")
        or ""
    )
    admin_token = (
        request.query_params.get("admin_token")
        or request.headers.get("X-Admin-Token")
        or ""
    )
    return require_admin_context(platform=platform, user_id=user_id, admin_token=admin_token)


def is_platform_admin(platform: str, user_id: str) -> bool:
    normalized_platform = _normalize_platform(platform)
    normalized_user_id = user_id.strip()
    if not normalized_user_id:
        return False
    try:
        from src.platform.admin_registry import get_admin_ids

        if normalized_user_id in get_admin_ids(normalized_platform):
            return True
    except Exception:
        pass
    try:
        from src.platform.org_graph import OrgGraphService

        return OrgGraphService().is_admin(normalized_platform, normalized_user_id)
    except Exception:
        return False


def _verify_admin_console_token(
    *,
    platform: str,
    user_id: str,
    token: str,
    now: float | None = None,
) -> bool:
    secret = _admin_secret()
    if not secret or not token or "." not in token:
        return False
    body, _, sig = token.partition(".")
    if not hmac.compare_digest(_sign(body, secret), sig):
        return False
    try:
        payload = json.loads(_unb64(body).decode("utf-8"))
    except Exception:
        return False
    current = int(time.time() if now is None else now)
    if str(payload.get("platform", "")) != _normalize_platform(platform):
        return False
    if str(payload.get("user_id", "")) != user_id.strip():
        return False
    try:
        exp = int(payload.get("exp", 0))
    except (TypeError, ValueError):
        return False
    return current <= exp


def _admin_secret() -> str:
    return os.environ.get("ANT_COLONY_ADMIN_SESSION_SECRET", "") or os.environ.get("ANT_COLONY_AUTH_TOKEN", "")


def _normalize_platform(platform: str) -> str:
    normalized = platform.strip().lower() or "wecom"
    if normalized not in {"wecom", "feishu", "dingtalk"}:
        raise HTTPException(400, f"不支持的平台：{platform}")
    return normalized


def _sign(body: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).digest()
    return _b64(digest)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)
