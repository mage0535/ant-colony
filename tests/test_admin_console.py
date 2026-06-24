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


def test_admin_employee_bot_activation_uses_im_admin_context() -> None:
    from src.web.dashboard import EmployeeBotActivationRequest, admin_activate_employee_bot

    request = _request("/api/v1/admin/employee-bots/activate")
    fake_assignment = {"platform": "wecom", "user_id": "u2", "status": "active", "notify_status": "sent"}

    with patch("src.web.dashboard.require_admin_context_from_request", return_value={"platform": "wecom", "user_id": "u-admin"}), \
         patch("src.platform.employee_bot_service.activate_employee_bot", return_value=fake_assignment) as activate:
        result = admin_activate_employee_bot(
            EmployeeBotActivationRequest(platform="wecom", user_id="u2"),
            request,
        )

    assert result["assignment"]["status"] == "active"
    assert activate.call_args.kwargs["activated_by"] == "u-admin"
    assert activate.call_args.kwargs["user_id"] == "u2"


def test_admin_employee_bot_list_requires_admin_context() -> None:
    from src.web.dashboard import admin_list_employee_bots

    request = _request("/api/v1/admin/employee-bots")
    with patch("src.web.dashboard.require_admin_context_from_request", return_value={"platform": "wecom", "user_id": "u-admin"}), \
         patch("src.platform.employee_bot_service.list_employee_bot_assignments", return_value=[{"user_id": "u2"}]):
        result = admin_list_employee_bots(request, platform="wecom")

    assert result["assignments"][0]["user_id"] == "u2"


def test_collect_knowledge_rejects_write_without_permission() -> None:
    from src.web.dashboard import KnowledgeCollectRequest, collect_knowledge

    with patch("src.knowledge.acl.resolve_role", return_value=type("RoleValue", (), {"value": 1})()), \
         patch("src.knowledge.acl.may_write", return_value=False):
        with pytest.raises(HTTPException) as exc_info:
            collect_knowledge(
                KnowledgeCollectRequest(
                    text="hello",
                    title="标题",
                    owner_type="organization",
                    owner_id="*",
                    user_id="u1",
                )
            )

    assert exc_info.value.status_code == 403


def test_admin_console_page_contains_material_business_sections() -> None:
    from src.web.dashboard import admin_console_page

    html = admin_console_page().body.decode("utf-8")

    assert "--md-primary:#0b57d0" in html
    assert "平台 Bot 开通" in html
    assert "员工 AI 助手" in html
    assert "开通并通知员工" in html
    assert "保存并接管企业微信" in html


def test_knowledge_management_page_contains_business_operations() -> None:
    from src.web.dashboard import knowledge_management_page

    html = knowledge_management_page().body.decode("utf-8")

    assert "--md-primary:#0b57d0" in html
    assert "新增到知识库" in html
    assert "升级知识条目" in html
    assert "导入公司说明书" in html
    assert "按企业微信组织权限自动适配" in html


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
