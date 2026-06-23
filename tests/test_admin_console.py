from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from fastapi import HTTPException, Request, Response

from src.web.dashboard import auth_and_rate_limit


def _request(path: str, query: str = "", host: str = "10.0.0.8") -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("utf-8"),
            "query_string": query.encode("utf-8"),
            "headers": [],
            "client": (host, 12345),
            "server": ("127.0.0.1", 18092),
        }
    )


def test_admin_console_token_requires_im_admin() -> None:
    from src.web.admin_auth import create_admin_console_token, require_admin_context

    with patch.dict("os.environ", {"ANT_COLONY_ADMIN_SESSION_SECRET": "secret"}, clear=False):
        token = create_admin_console_token(platform="wecom", user_id="u-admin", now=1000)
        with patch("src.web.admin_auth.is_platform_admin", return_value=True):
            context = require_admin_context(platform="wecom", user_id="u-admin", admin_token=token, now=1001)

    assert context["platform"] == "wecom"
    assert context["user_id"] == "u-admin"


def test_admin_console_token_rejects_non_admin_user() -> None:
    from src.web.admin_auth import create_admin_console_token, require_admin_context

    with patch.dict("os.environ", {"ANT_COLONY_ADMIN_SESSION_SECRET": "secret"}, clear=False):
        token = create_admin_console_token(platform="wecom", user_id="u1", now=1000)
        with patch("src.web.admin_auth.is_platform_admin", return_value=False):
            with pytest.raises(HTTPException) as exc_info:
                require_admin_context(platform="wecom", user_id="u1", admin_token=token, now=1001)

    assert exc_info.value.status_code == 403


def test_admin_api_uses_admin_auth_instead_of_dashboard_bearer() -> None:
    request = _request("/api/v1/admin/profile")

    async def call_next(_: Request) -> Response:
        return Response("ok")

    with patch("src.web.dashboard.require_auth") as auth, patch("src.web.dashboard.check_rate_limit"):
        response = asyncio.run(auth_and_rate_limit(request, call_next))

    assert response.status_code == 200
    auth.assert_not_called()


def test_admin_activate_bot_sets_activated_by_from_im_user() -> None:
    from src.web.dashboard import PlatformBotActivationRequest, admin_activate_platform_bot

    request = _request("/api/v1/admin/platform/bots/wecom/activate")
    fake_result = {
        "platform": "wecom",
        "enabled": True,
        "managed_by_platform": True,
        "configured_keys": ["bot_id", "bot_secret"],
        "visibility_scope": "all",
        "display_name": "企业 AI 助手",
        "auto_permissions": ["docs.full"],
        "restart_required": True,
        "next_action": "企业微信凭据已保存，重启对应 Bot/网关服务后生效。",
    }

    with patch("src.web.dashboard.require_admin_context_from_request", return_value={"platform": "wecom", "user_id": "u-admin"}), \
         patch("src.web.dashboard.activate_platform_bot_api", return_value=fake_result) as activate:
        result = admin_activate_platform_bot(
            "wecom",
            PlatformBotActivationRequest(credentials={"bot_id": "bot-1", "bot_secret": "sec-1"}),
            request,
        )

    assert result["enabled"] is True
    assert activate.call_args.args[1].activated_by == "u-admin"


def test_create_admin_console_link_includes_signed_token() -> None:
    from scripts.create_admin_console_link import build_admin_console_link

    with patch.dict("os.environ", {"ANT_COLONY_ADMIN_SESSION_SECRET": "secret"}, clear=False):
        link = build_admin_console_link(
            base_url="http://example.test",
            platform="wecom",
            user_id="u-admin",
            ttl_seconds=60,
        )

    assert link.startswith("http://example.test/admin/console?")
    assert "platform=wecom" in link
    assert "user_id=u-admin" in link
    assert "admin_token=" in link
