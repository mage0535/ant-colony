from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request


DEFAULT_ADMIN_SESSION_TTL_SECONDS = 3600
DEFAULT_ADMIN_REFRESH_GRACE_SECONDS = 86400
DEFAULT_USER_SESSION_TTL_SECONDS = 86400

_revoked_jtis: dict[str, float] = {}

# Cleanup expired JTIs periodically
def _cleanup_revoked_jtis(now: float | None = None):
    current = now if now is not None else time.time()
    expired = [jti for jti, exp in _revoked_jtis.items() if exp <= current]
    for jti in expired:
        del _revoked_jtis[jti]


def revoke_token(*, token: str):
    """Mark a token as revoked so it cannot be reused."""
    try:
        body, _, _sig = token.partition(".")
        payload = json.loads(_unb64(body).decode("utf-8"))
        jti = payload.get("jti", "")
        exp = int(payload.get("exp", 0))
        if jti:
            _revoked_jtis[jti] = exp + _admin_refresh_grace_seconds()
    except Exception:
        pass


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
        "iat": issued_at,
        "exp": issued_at + int(ttl_seconds),
        "jti": uuid.uuid4().hex,
    }
    body = _b64(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    sig = _sign(body, secret)
    return f"{body}.{sig}"


def create_im_user_token(
    *,
    platform: str,
    user_id: str,
    ttl_seconds: int = DEFAULT_USER_SESSION_TTL_SECONDS,
    now: float | None = None,
) -> str:
    secret = _admin_secret()
    if not secret:
        raise RuntimeError("ANT_COLONY_ADMIN_SESSION_SECRET or ANT_COLONY_AUTH_TOKEN is required")
    issued_at = int(time.time() if now is None else now)
    payload = {
        "kind": "im_user",
        "platform": _normalize_platform(platform),
        "user_id": user_id.strip(),
        "iat": issued_at,
        "exp": issued_at + int(ttl_seconds),
        "jti": uuid.uuid4().hex,
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


def require_console_context(
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
        raise HTTPException(401, "后台访问令牌无效或已过期")
    if is_platform_admin(normalized_platform, normalized_user_id):
        return {"platform": normalized_platform, "user_id": normalized_user_id, "role": "admin"}
    if is_hr_specialist(normalized_platform, normalized_user_id):
        return {"platform": normalized_platform, "user_id": normalized_user_id, "role": "hr_specialist"}
    raise HTTPException(403, "当前企业 IM 用户不是平台管理员或人事专员")


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


def require_console_context_from_request(request: Request) -> dict[str, Any]:
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
    return require_console_context(platform=platform, user_id=user_id, admin_token=admin_token)


def require_user_context_from_request(request: Request) -> dict[str, Any]:
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
    user_token = (
        request.query_params.get("user_token")
        or request.headers.get("X-User-Token")
        or ""
    )
    normalized_platform = _normalize_platform(platform)
    normalized_user_id = user_id.strip()
    if not normalized_user_id:
        raise HTTPException(401, "缺少企业 IM 用户身份")
    if not _verify_im_user_token(
        platform=normalized_platform,
        user_id=normalized_user_id,
        token=user_token,
    ):
        raise HTTPException(401, "用户访问令牌无效或已过期")
    return {"platform": normalized_platform, "user_id": normalized_user_id, "role": "user"}


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


def is_hr_specialist(platform: str, user_id: str) -> bool:
    normalized_platform = _normalize_platform(platform)
    normalized_user_id = user_id.strip()
    if not normalized_user_id:
        return False
    try:
        from src.platform.hr_specialist_service import is_hr_specialist as check_hr_specialist

        return check_hr_specialist(normalized_platform, normalized_user_id)
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
    jti = payload.get("jti", "")
    _cleanup_revoked_jtis(now)
    if jti and jti in _revoked_jtis:
        return False
    return current <= exp


def decode_and_refresh_admin_token(
    *,
    token: str,
    ttl_seconds: int = DEFAULT_ADMIN_SESSION_TTL_SECONDS,
    now: float | None = None,
) -> str:
    """Given a recently expired token (HMAC still valid), return a fresh token."""
    secret = _admin_secret()
    if not secret or not token or "." not in token:
        raise HTTPException(401, "管理员访问令牌无效")
    body, _, sig = token.partition(".")
    if not hmac.compare_digest(_sign(body, secret), sig):
        raise HTTPException(401, "管理员访问令牌签名无效")
    try:
        payload = json.loads(_unb64(body).decode("utf-8"))
    except Exception:
        raise HTTPException(401, "管理员访问令牌格式错误")
    platform = str(payload.get("platform", ""))
    user_id = str(payload.get("user_id", ""))
    if not platform or not user_id:
        raise HTTPException(401, "管理员访问令牌内容无效")
    try:
        exp = int(payload.get("exp", 0))
    except (TypeError, ValueError):
        raise HTTPException(401, "管理员访问令牌内容无效")
    current = int(time.time() if now is None else now)
    if current > exp + _admin_refresh_grace_seconds():
        raise HTTPException(401, "管理员访问令牌已过期，请从 Bot 重新打开管理员控制台")
    jti = payload.get("jti", "")
    _cleanup_revoked_jtis(now)
    if jti and jti in _revoked_jtis:
        raise HTTPException(401, "管理员访问令牌已失效")
    return create_admin_console_token(platform=platform, user_id=user_id, ttl_seconds=ttl_seconds, now=now)


def _verify_im_user_token(*, platform: str, user_id: str, token: str, now: float | None = None) -> bool:
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
    if str(payload.get("kind", "")) != "im_user":
        return False
    if str(payload.get("platform", "")) != _normalize_platform(platform):
        return False
    if str(payload.get("user_id", "")) != user_id.strip():
        return False
    try:
        exp = int(payload.get("exp", 0))
    except (TypeError, ValueError):
        return False
    jti = payload.get("jti", "")
    _cleanup_revoked_jtis(now)
    if jti and jti in _revoked_jtis:
        return False
    return current <= exp


def _admin_secret() -> str:
    return (
        os.environ.get("ANT_COLONY_ADMIN_SESSION_SECRET", "")
        or os.environ.get("ANT_COLONY_AUTH_TOKEN", "")
        or _admin_secret_from_env_file()
    )


def _admin_secret_from_env_file() -> str:
    candidates = [
        Path(os.getcwd()) / "infra" / ".env.wecom",
    ]
    if os.environ.get("ANT_COLONY_HOME"):
        candidates.append(Path(os.environ["ANT_COLONY_HOME"]) / "infra" / ".env.wecom")
    candidates.append(Path.home() / "ant-colony" / "infra" / ".env.wecom")
    for path in candidates:
        try:
            if not path.is_file():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key, value = stripped.split("=", 1)
                if key.strip() in {"ANT_COLONY_ADMIN_SESSION_SECRET", "ANT_COLONY_AUTH_TOKEN"}:
                    return value.strip().strip('"').strip("'")
        except OSError:
            continue
    return ""


def _admin_refresh_grace_seconds() -> int:
    raw = os.environ.get("ANT_COLONY_ADMIN_REFRESH_GRACE_SECONDS", "").strip()
    if not raw:
        return DEFAULT_ADMIN_REFRESH_GRACE_SECONDS
    try:
        parsed = int(raw)
    except ValueError:
        return DEFAULT_ADMIN_REFRESH_GRACE_SECONDS
    return max(0, min(parsed, 7 * 86400))


def _normalize_platform(platform: str) -> str:
    normalized = str(platform or "wecom").strip().lower() or "wecom"
    aliases = {
        "wecom_bot": "wecom",
        "wecom_bot_ws": "wecom",
        "wecom_callback": "wecom",
        "企业微信": "wecom",
        "企微": "wecom",
        "feishu_bot": "feishu",
        "lark": "feishu",
        "lark_bot": "feishu",
        "飞书": "feishu",
        "dingtalk_bot": "dingtalk",
        "钉钉": "dingtalk",
    }
    normalized = aliases.get(normalized, normalized)
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
