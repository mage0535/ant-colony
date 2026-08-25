from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
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


def test_admin_console_token_uses_wecom_env_file_when_process_env_missing(tmp_path, monkeypatch) -> None:
    from src.web.admin_auth import create_admin_console_token, require_admin_context

    env_dir = tmp_path / "infra"
    env_dir.mkdir()
    (env_dir / ".env.wecom").write_text("ANT_COLONY_ADMIN_SESSION_SECRET=file-secret\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANT_COLONY_ADMIN_SESSION_SECRET", raising=False)
    monkeypatch.delenv("ANT_COLONY_AUTH_TOKEN", raising=False)

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


def test_console_token_accepts_hr_specialist_limited_role() -> None:
    from src.web.admin_auth import create_admin_console_token, require_console_context

    with patch.dict("os.environ", {"ANT_COLONY_ADMIN_SESSION_SECRET": "secret"}, clear=False):
        token = create_admin_console_token(platform="wecom", user_id="u-hr", now=1000)
        with patch("src.web.admin_auth.is_platform_admin", return_value=False), \
             patch("src.web.admin_auth.is_hr_specialist", return_value=True):
            context = require_console_context(platform="wecom", user_id="u-hr", admin_token=token, now=1001)

    assert context["platform"] == "wecom"
    assert context["user_id"] == "u-hr"
    assert context["role"] == "hr_specialist"


def test_admin_profile_preserves_console_role_for_hr_specialist() -> None:
    from src.web.dashboard import admin_profile

    request = _request("/api/v1/admin/profile")
    with patch("src.web.dashboard.require_console_context_from_request", return_value={"platform": "wecom", "user_id": "u-hr", "role": "hr_specialist"}), \
         patch("src.knowledge.acl.resolve_role", return_value=type("Role", (), {"name": "self", "value": 1})()), \
         patch("src.knowledge.acl.visible_scopes", return_value=[]), \
         patch("src.platform.org_graph.OrgGraphService.get_user_profile", return_value={"name": "李四", "departments": ["综合管理部"]}):
        result = admin_profile(request)

    assert result["role"] == "hr_specialist"
    assert result["knowledge_role"] == "self"
    assert result["can_manage_leave"] is True
    assert result["can_manage_platform"] is False


def test_admin_console_token_refresh_allows_recently_expired_token() -> None:
    from src.web.admin_auth import create_admin_console_token, decode_and_refresh_admin_token, require_admin_context

    with patch.dict("os.environ", {"ANT_COLONY_ADMIN_SESSION_SECRET": "secret", "ANT_COLONY_ADMIN_REFRESH_GRACE_SECONDS": "60"}, clear=False), patch(
        "src.web.admin_auth.is_platform_admin", return_value=True
    ):
        token = create_admin_console_token(platform="wecom", user_id="u-admin", ttl_seconds=10, now=1000)
        refreshed = decode_and_refresh_admin_token(token=token, now=1020)
        context = require_admin_context(platform="wecom", user_id="u-admin", admin_token=refreshed, now=1021)

    assert context["user_id"] == "u-admin"


def test_admin_console_token_refresh_rejects_stale_expired_token() -> None:
    from src.web.admin_auth import create_admin_console_token, decode_and_refresh_admin_token

    with patch.dict("os.environ", {"ANT_COLONY_ADMIN_SESSION_SECRET": "secret", "ANT_COLONY_ADMIN_REFRESH_GRACE_SECONDS": "60"}, clear=False):
        token = create_admin_console_token(platform="wecom", user_id="u-admin", ttl_seconds=10, now=1000)
        with pytest.raises(HTTPException) as exc_info:
            decode_and_refresh_admin_token(token=token, now=1071)

    assert exc_info.value.status_code == 401
    assert "重新打开管理员控制台" in str(exc_info.value.detail)


def test_admin_console_token_refresh_keeps_revoked_token_blocked_after_expiry() -> None:
    from src.web.admin_auth import create_admin_console_token, decode_and_refresh_admin_token, revoke_token

    with patch.dict("os.environ", {"ANT_COLONY_ADMIN_SESSION_SECRET": "secret", "ANT_COLONY_ADMIN_REFRESH_GRACE_SECONDS": "60"}, clear=False):
        token = create_admin_console_token(platform="wecom", user_id="u-admin", ttl_seconds=10, now=1000)
        revoke_token(token=token)
        with pytest.raises(HTTPException) as exc_info:
            decode_and_refresh_admin_token(token=token, now=1020)

    assert exc_info.value.status_code == 401
    assert "已失效" in str(exc_info.value.detail)


def test_admin_api_uses_admin_auth_instead_of_dashboard_bearer() -> None:
    request = _request("/api/v1/admin/profile")

    async def call_next(_: Request) -> Response:
        return Response("ok")

    with patch("src.web.dashboard.require_auth") as auth, patch("src.web.dashboard.check_rate_limit"):
        response = asyncio.run(auth_and_rate_limit(request, call_next))

    assert response.status_code == 200
    auth.assert_not_called()


def test_user_entry_api_is_public_and_skips_dashboard_bearer() -> None:
    request = _request("/api/v1/user/entry-payloads")

    async def call_next(_: Request) -> Response:
        return Response("ok")

    with patch("src.web.dashboard.require_auth") as auth, patch("src.web.dashboard.check_rate_limit"):
        response = asyncio.run(auth_and_rate_limit(request, call_next))

    assert response.status_code == 200
    auth.assert_not_called()


def test_ratemin_ingest_api_is_public_and_uses_own_token() -> None:
    request = _request("/api/v1/site/ratemin/ingest")

    async def call_next(_: Request) -> Response:
        return Response("ok")

    with patch("src.web.dashboard.require_auth") as auth, patch("src.web.dashboard.check_rate_limit"):
        response = asyncio.run(auth_and_rate_limit(request, call_next))

    assert response.status_code == 200
    auth.assert_not_called()


def test_web_search_more_page_is_public_and_skips_dashboard_bearer() -> None:
    request = _request("/api/v1/web-search/more", "q=topic&page=2")

    async def call_next(_: Request) -> Response:
        return Response("ok")

    with patch("src.web.dashboard.require_auth") as auth, patch("src.web.dashboard.check_rate_limit"):
        response = asyncio.run(auth_and_rate_limit(request, call_next))

    assert response.status_code == 200
    auth.assert_not_called()


def test_web_search_more_page_linkifies_result_urls() -> None:
    from src.web.dashboard import web_search_more_page

    with patch("src.tools.web_research_service.web_search_aggregate_page_cached", return_value="Title\nhttps://example.com/a"):
        response = web_search_more_page(q="topic", page=2, page_size=20)

    body = response.body.decode("utf-8")
    assert "联网检索结果" in body
    assert 'href="https://example.com/a"' in body
    assert "当前第 2 页" in body


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
        "credential_sources": {"bot_id": "当前服务环境变量"},
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


def test_admin_wecom_mcp_status_uses_admin_context() -> None:
    from src.web.dashboard import admin_wecom_mcp_status

    request = _request("/api/v1/admin/wecom/mcp/status")
    fake_status = {"doc": {"configured": True}, "todo": {"configured": False}}
    with patch("src.web.dashboard.require_admin_context_from_request", return_value={"platform": "wecom", "user_id": "u-admin"}), \
         patch("src.platform.wecom_robot_mcp_provider.get_wecom_robot_mcp_status", return_value=fake_status) as status:
        result = admin_wecom_mcp_status(request, discover=True)

    assert result == fake_status
    status.assert_called_once_with(discover=True)


def test_admin_public_data_source_management_requires_admin_context() -> None:
    from src.web.dashboard import (
        PublicDataSourceRequest,
        PublicDataSourceTestRequest,
        admin_delete_public_data_source,
        admin_public_data_sources,
        admin_save_public_data_source,
        admin_test_public_data_source,
    )

    request = _request("/api/v1/admin/public-data/sources")
    with patch("src.web.dashboard.require_admin_context_from_request", return_value={"platform": "wecom", "user_id": "u-admin"}), \
         patch("src.platform.public_data_service.list_data_source_configs", return_value=[{"kind": "flight"}]) as list_sources, \
         patch("src.platform.public_data_service.save_data_source_config", return_value={"kind": "flight", "configured": True}) as save_source, \
         patch("src.platform.public_data_service.test_data_source", return_value={"kind": "flight", "ok": True}) as test_source, \
         patch("src.platform.public_data_service.delete_data_source_config", return_value={"kind": "flight", "deleted": True}) as delete_source:
        listed = admin_public_data_sources(request)
        saved = admin_save_public_data_source(PublicDataSourceRequest(kind="flight", label="航班查询"), request)
        tested = admin_test_public_data_source(PublicDataSourceTestRequest(kind="flight", query="明天去北京"), request)
        deleted = admin_delete_public_data_source("flight", request)

    assert listed["sources"][0]["kind"] == "flight"
    assert saved["source"]["configured"] is True
    assert tested["ok"] is True
    assert deleted["deleted"] is True
    list_sources.assert_called_once()
    save_source.assert_called_once()
    test_source.assert_called_once_with("flight", query="明天去北京", params={})
    delete_source.assert_called_once_with("flight")


def test_admin_integration_center_requires_admin_context() -> None:
    from src.web.dashboard import IntegrationTestRequest, admin_integrations, admin_test_integration

    request = _request("/api/v1/admin/integrations")
    fake_context = {"platform": "wecom", "user_id": "u-admin"}
    fake_list = {"items": [{"id": "models:profiles", "status": "ready"}], "summary": {"total": 1}}
    fake_test = {"integration_id": "models:profiles", "ok": True, "result": "ok"}
    with patch("src.web.dashboard.require_admin_context_from_request", return_value=fake_context), \
         patch("src.platform.integration_management_service.list_integrations", return_value=fake_list) as list_integrations, \
         patch("src.platform.integration_management_service.test_integration", return_value=fake_test) as test_integration:
        listed = admin_integrations(request)
        tested = admin_test_integration(IntegrationTestRequest(integration_id="models:profiles", query="test"), request)

    assert listed == fake_list
    assert tested == fake_test
    list_integrations.assert_called_once_with(platform="wecom", user_id="u-admin")
    test_integration.assert_called_once_with("models:profiles", platform="wecom", user_id="u-admin", query="test")


def test_admin_wecom_mcp_config_saves_urls() -> None:
    from src.web.dashboard import WeComMcpConfigRequest, admin_wecom_mcp_config

    request = _request("/api/v1/admin/wecom/mcp/config")
    fake_result = {
        "saved_keys": ["WECOM_ROBOT_DOC_MCP_URL"],
        "status": {"doc": {"url_masked": "https://example.test?apikey=abc...xyz"}},
    }
    with patch("src.web.dashboard.require_admin_context_from_request", return_value={"platform": "wecom", "user_id": "u-admin"}), \
         patch("src.platform.wecom_robot_mcp_provider.save_wecom_robot_mcp_urls", return_value=fake_result) as save:
        result = admin_wecom_mcp_config(
            WeComMcpConfigRequest(doc_mcp_url="https://example.test?apikey=secret", todo_mcp_url=""),
            request,
        )

    assert result == fake_result
    save.assert_called_once_with(doc_url="https://example.test?apikey=secret", todo_url="")


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


def test_admin_employee_bot_welcome_requires_admin_context() -> None:
    from src.web.dashboard import EmployeeBotActivationRequest, admin_send_employee_bot_welcome

    request = _request("/api/v1/admin/employee-bots/welcome")
    fake_result = {"notify_status": "sent", "assignment": {"user_id": "u2", "status": "active"}}
    with patch("src.web.dashboard.require_admin_context_from_request", return_value={"platform": "wecom", "user_id": "u-admin"}), \
         patch("src.platform.employee_bot_service.send_employee_bot_welcome", return_value=fake_result) as send_welcome:
        result = admin_send_employee_bot_welcome(
            EmployeeBotActivationRequest(platform="wecom", user_id="u2", display_name="企业 AI 助手"),
            request,
        )

    assert result["notify_status"] == "sent"
    send_welcome.assert_called_once_with(platform="wecom", user_id="u2", display_name="企业 AI 助手")


def test_admin_user_details_api_requires_admin_context() -> None:
    from src.web.dashboard import admin_user_details

    request = _request("/api/v1/admin/users")
    fake = {"platform": "wecom", "users": [{"user_id": "u2", "bot_status": "active"}]}
    with patch("src.web.dashboard.require_console_context_from_request", return_value={"platform": "wecom", "user_id": "u-admin", "role": "admin"}), \
         patch("src.platform.user_management_service.list_admin_user_details", return_value=fake) as list_users:
        result = admin_user_details(request, platform="wecom", sync=False)

    assert result["users"][0]["user_id"] == "u2"
    list_users.assert_called_once_with(platform="wecom", sync=False)


def test_admin_batch_employee_bots_updates_selected_users() -> None:
    from src.web.dashboard import EmployeeBotBatchRequest, admin_batch_employee_bots

    request = _request("/api/v1/admin/employee-bots/batch")
    with patch("src.web.dashboard.require_admin_context_from_request", return_value={"platform": "wecom", "user_id": "u-admin"}), \
         patch("src.platform.employee_bot_service.activate_employee_bot", side_effect=lambda **kw: {"user_id": kw["user_id"], "status": "active"}) as activate:
        result = admin_batch_employee_bots(EmployeeBotBatchRequest(platform="wecom", user_ids=["u1", "u2"], status="active"), request)

    assert result["updated"] == 2
    assert activate.call_count == 2


def test_admin_broadcast_uses_admin_context_sender() -> None:
    from src.web.dashboard import OrganizationBroadcastRequest, admin_broadcast_organization

    request = _request("/api/v1/admin/organization/broadcast")
    fake_result = {"ok": True, "sent": 2, "skipped": 1}

    with patch("src.web.dashboard.require_admin_context_from_request", return_value={"platform": "wecom", "user_id": "u-admin"}), \
         patch("src.platform.organization_broadcast_service.broadcast_to_organization", return_value=fake_result) as broadcast:
        result = admin_broadcast_organization(
            OrganizationBroadcastRequest(platform="wecom", target="技术部", message="下班关灯"),
            request,
        )

    assert result == fake_result
    broadcast.assert_called_once_with(
        platform="wecom",
        sender_user_id="u-admin",
        target="技术部",
        message="下班关灯",
    )


def test_admin_model_management_apis() -> None:
    from src.web.dashboard import ModelDefaultRequest, ModelDiscoverRequest, ModelProfileRequest, admin_delete_model_profile, admin_discover_models, admin_model_profiles, admin_save_model_profile, admin_set_default_model, admin_test_model_profile

    request = _request("/api/v1/admin/models")
    with patch("src.web.dashboard.require_admin_context_from_request", return_value={"platform": "wecom", "user_id": "u-admin"}), \
         patch("src.platform.model_management_service.list_model_profiles", return_value={"profiles": []}):
        assert admin_model_profiles(request)["profiles"] == []

    with patch("src.web.dashboard.require_admin_context_from_request", return_value={"platform": "wecom", "user_id": "u-admin"}), \
         patch("src.platform.model_management_service.save_model_profile", return_value={"profile_id": "default", "api_key_configured": True}) as save:
        result = admin_save_model_profile(ModelProfileRequest(profile_id="default", model_name="gpt-4.1-mini"), request)
    assert result["profile"]["profile_id"] == "default"
    assert save.call_args.args[0]["model_name"] == "gpt-4.1-mini"

    with patch("src.web.dashboard.require_admin_context_from_request", return_value={"platform": "wecom", "user_id": "u-admin"}), \
         patch("src.platform.model_management_service.discover_models", return_value={"ok": True, "models": [{"id": "m"}]}):
        result = admin_discover_models(ModelDiscoverRequest(api_key="sk-test"), request)
    assert result["models"][0]["id"] == "m"

    with patch("src.web.dashboard.require_admin_context_from_request", return_value={"platform": "wecom", "user_id": "u-admin"}), \
         patch("src.platform.model_management_service.set_default_model_profile", return_value={"ok": True, "profile_id": "default"}) as set_default:
        result = admin_set_default_model(ModelDefaultRequest(profile_id="default"), request)
    assert result["profile_id"] == "default"
    set_default.assert_called_once_with("default")

    with patch("src.web.dashboard.require_admin_context_from_request", return_value={"platform": "wecom", "user_id": "u-admin"}), \
         patch("src.platform.model_management_service.test_model_profile", return_value={"ok": True, "profile_id": "default", "response": "正常"}) as test_profile:
        result = admin_test_model_profile(ModelDefaultRequest(profile_id="default"), request)
    assert result["ok"] is True
    assert result["response"] == "正常"
    test_profile.assert_called_once_with("default")

    with patch("src.web.dashboard.require_admin_context_from_request", return_value={"platform": "wecom", "user_id": "u-admin"}), \
         patch("src.platform.model_management_service.delete_model_profile", return_value={"ok": True, "profile_id": "default", "deleted": True}) as delete_profile:
        result = admin_delete_model_profile("default", request)
    assert result["deleted"] is True
    delete_profile.assert_called_once_with("default")


def test_admin_mail_account_apis_require_admin_context() -> None:
    from src.web.dashboard import (
        MailAccountRequest,
        MailAccountStatusRequest,
        admin_delete_mail_account,
        admin_list_mail_accounts,
        admin_save_mail_account,
        admin_set_mail_account_status,
        admin_test_mail_account,
    )

    request = _request("/api/v1/admin/mail/accounts")
    admin_context = {"platform": "wecom", "user_id": "u-admin"}

    with patch("src.web.dashboard.require_admin_context_from_request", return_value=admin_context), \
         patch("src.platform.mail_account_service.list_mail_accounts", return_value={"accounts": [{"user_id": "u1"}]}) as list_accounts:
        result = admin_list_mail_accounts(request, platform="wecom")
    assert result["accounts"][0]["user_id"] == "u1"
    list_accounts.assert_called_once_with(platform="wecom", user_id="")

    payload = MailAccountRequest(
        platform="wecom",
        user_id="u1",
        email_address="u1@example.com",
        imap_host="imap.example.com",
        username="u1@example.com",
        password="secret",
    )
    with patch("src.web.dashboard.require_admin_context_from_request", return_value=admin_context), \
         patch("src.platform.mail_account_service.save_mail_account", return_value={"user_id": "u1", "password_configured": True}) as save:
        result = admin_save_mail_account(payload, request)
    assert result["account"]["password_configured"] is True
    assert save.call_args.kwargs["updated_by"] == "u-admin"
    assert "secret" not in str(result)

    with patch("src.web.dashboard.require_admin_context_from_request", return_value=admin_context), \
         patch("src.platform.mail_account_service.set_mail_account_status", return_value={"user_id": "u1", "enabled": False}) as status:
        result = admin_set_mail_account_status(MailAccountStatusRequest(platform="wecom", user_id="u1", enabled=False), request)
    assert result["account"]["enabled"] is False
    status.assert_called_once_with("wecom", "u1", enabled=False, updated_by="u-admin")

    with patch("src.web.dashboard.require_admin_context_from_request", return_value=admin_context), \
         patch("src.platform.mail_account_service.summarize_user_mailbox", return_value="邮箱未读统计") as test_mail:
        result = admin_test_mail_account(MailAccountStatusRequest(platform="wecom", user_id="u1"), request)
    assert result["result"] == "邮箱未读统计"
    assert result["ok"] is True
    test_mail.assert_called_once_with("wecom", "u1", limit=3)

    with patch("src.web.dashboard.require_admin_context_from_request", return_value=admin_context), \
         patch("src.platform.mail_account_service.delete_mail_account", return_value={"deleted": True}) as delete:
        result = admin_delete_mail_account("wecom", "u1", request)
    assert result["deleted"] is True
    delete.assert_called_once_with("wecom", "u1")


def test_admin_leave_negative_probe_apis_require_admin_context() -> None:
    from src.web.dashboard import (
        LeaveBalanceBatchTargetRequest,
        LeaveBalanceTargetRequest,
        LeaveNegativeProbeRequest,
        admin_apply_leave_balance_target_batch,
        admin_apply_leave_balance_target,
        admin_leave_negative_probe,
        admin_leave_negative_probe_results,
    )

    request = _request("/api/v1/admin/leave/negative-probe")
    admin_context = {"platform": "wecom", "user_id": "u-admin", "role": "admin"}

    with patch("src.web.dashboard.require_console_context_from_request", return_value=admin_context), \
         patch("src.platform.leave_quota_service.list_negative_probe_results", return_value=[{"user_id": "u1"}]) as listed:
        result = admin_leave_negative_probe_results(request, platform="wecom")
    assert result["results"][0]["user_id"] == "u1"
    listed.assert_called_once_with(platform="wecom")

    probe_req = LeaveNegativeProbeRequest(platform="wecom", user_id="u1", vacation_id=7, negative_duration=-86400)
    with patch("src.web.dashboard.require_console_context_from_request", return_value=admin_context), \
         patch("src.platform.leave_quota_service.probe_negative_leave_quota", return_value={"negative_supported": None}) as probe:
        result = admin_leave_negative_probe(probe_req, request)
    assert result["result"]["negative_supported"] is None
    probe.assert_called_once()
    assert probe.call_args.kwargs["operator_user_id"] == "u-admin"
    assert probe.call_args.kwargs["confirm_live_write"] is False

    adjust_req = LeaveBalanceTargetRequest(
        platform="wecom",
        user_id="u1",
        vacation_id=7,
        target_leftduration=-86400,
        time_attr=1,
        reason="测试欠假",
        allow_local_negative=True,
    )
    with patch("src.web.dashboard.require_console_context_from_request", return_value=admin_context), \
         patch("src.platform.leave_quota_service.apply_leave_balance_target", return_value={"mode": "local_negative_ledger"}) as apply_target:
        result = admin_apply_leave_balance_target(adjust_req, request)
    assert result["result"]["mode"] == "local_negative_ledger"
    assert apply_target.call_args.kwargs["operator_user_id"] == "u-admin"

    batch_req = LeaveBalanceBatchTargetRequest(
        platform="wecom",
        user_ids=["u1", "u2", "u1"],
        vacation_id=7,
        target_leftduration=86400,
        time_attr=1,
        reason="部门统一补录加班调休",
        allow_local_negative=True,
    )
    with patch("src.web.dashboard.require_console_context_from_request", return_value=admin_context), \
         patch("src.platform.leave_quota_service.apply_leave_balance_target", return_value={"mode": "updated"}) as apply_batch:
        result = admin_apply_leave_balance_target_batch(batch_req, request)
    assert result["updated"] == 2
    assert result["failed"] == 0
    assert [call.kwargs["user_id"] for call in apply_batch.call_args_list] == ["u1", "u2"]


def test_admin_leave_form_notice_resolves_employee_name(tmp_path, monkeypatch) -> None:
    from src.store.database import Database
    from src.web.dashboard import admin_leave_form_notice

    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "ant.db"))
    Database.get(str(tmp_path / "ant.db")).close()
    conn = Database.get().connect()
    conn.execute("INSERT INTO org_users(platform,user_id,name) VALUES(?,?,?)", ("wecom", "u-zhang", "张三"))
    conn.commit()

    request = _request("/api/v1/admin/leave/form-notice")
    admin_context = {"platform": "wecom", "user_id": "u-admin", "role": "hr_specialist"}
    with patch("src.web.dashboard.require_console_context_from_request", return_value=admin_context), \
         patch(
             "src.platform.leave_quota_service.build_employee_leave_form_notice",
             return_value="张三的动态提示",
         ) as build_notice:
        result = admin_leave_form_notice(request, user_query="张三", platform="wecom")
    assert result["notice"] == "张三的动态提示"
    assert result["user_id"] == "u-zhang"
    build_notice.assert_called_once_with(platform="wecom", user_id="u-zhang")


def test_admin_leave_workflow_notice_api_requires_admin_context() -> None:
    from src.web.dashboard import LeaveWorkflowNoticeRequest, admin_leave_workflow_notice

    request = _request("/api/v1/admin/leave/workflow-notice")
    admin_context = {"platform": "wecom", "user_id": "u-admin", "role": "admin"}

    with patch("src.web.dashboard.require_console_context_from_request", return_value=admin_context), \
         patch("src.platform.leave_quota_service.plan_leave_workflow_notice_update", return_value={"needs_update": True}) as planned:
        preview = admin_leave_workflow_notice(
            LeaveWorkflowNoticeRequest(template_id="tpl1", apply_update=False),
            request,
        )

    with patch("src.web.dashboard.require_console_context_from_request", return_value=admin_context), \
         patch("src.platform.leave_quota_service.apply_leave_workflow_notice_update", return_value={"applied": True}) as applied:
        committed = admin_leave_workflow_notice(
            LeaveWorkflowNoticeRequest(template_id="tpl1", apply_update=True, notice_text="说明"),
            request,
        )

    planned.assert_called_once_with(template_id="tpl1", notice_text="")
    applied.assert_called_once_with(template_id="tpl1", notice_text="说明", operator_user_id="u-admin")
    assert preview["result"]["needs_update"] is True
    assert committed["result"]["applied"] is True


def test_admin_leave_workflow_notice_auto_resolves_template_id() -> None:
    from src.web.dashboard import LeaveWorkflowNoticeRequest, admin_leave_workflow_notice

    request = _request("/api/v1/admin/leave/workflow-notice")
    admin_context = {"platform": "wecom", "user_id": "u-admin", "role": "admin"}

    with patch("src.web.dashboard.require_console_context_from_request", return_value=admin_context), \
         patch(
             "src.platform.leave_quota_service.resolve_leave_workflow_template_id",
             return_value={"template_id": "tpl-auto", "source": "recent_approval_detail", "discovery": {}},
         ) as resolve_template, \
         patch("src.platform.leave_quota_service.plan_leave_workflow_notice_update", return_value={"needs_update": True}) as planned:
        result = admin_leave_workflow_notice(LeaveWorkflowNoticeRequest(template_id="", apply_update=False), request)

    resolve_template.assert_called_once_with(template_id="", platform="wecom")
    planned.assert_called_once_with(template_id="tpl-auto", notice_text="")
    assert result["result"]["template_resolution"]["source"] == "recent_approval_detail"


def test_admin_leave_form_notice_api_requires_admin_context() -> None:
    from src.web.dashboard import admin_leave_form_notice

    request = _request("/api/v1/admin/leave/form-notice")
    admin_context = {"platform": "wecom", "user_id": "u-admin", "role": "admin"}

    with patch("src.web.dashboard.require_console_context_from_request", return_value=admin_context), \
         patch(
             "src.platform.leave_quota_service.build_employee_leave_form_notice",
             return_value="调休假：欠公司 1 天，待后续加班调休冲抵",
         ) as build_notice:
        result = admin_leave_form_notice(request, user_id="u1", platform="wecom")

    build_notice.assert_called_once_with(platform="wecom", user_id="u1")
    assert "欠公司 1 天" in result["notice"]


def test_admin_leave_realtime_sync_apis_require_admin_context() -> None:
    from src.web.dashboard import (
        LeavePolicyRequest,
        admin_configure_leave_policy,
        admin_leave_realtime_status,
        admin_run_leave_realtime_sync,
        admin_sync_leave_policies,
    )

    request = _request("/api/v1/admin/leave/realtime-sync")
    admin_context = {"platform": "wecom", "user_id": "u-admin", "role": "admin"}

    with patch("src.web.dashboard.require_console_context_from_request", return_value=admin_context), \
         patch("src.platform.leave_quota_service.list_leave_realtime_status", return_value={"policies": []}) as status:
        result = admin_leave_realtime_status(request, platform="wecom")
    assert result["policies"] == []
    status.assert_called_once_with(platform="wecom")

    with patch("src.web.dashboard.require_console_context_from_request", return_value=admin_context), \
         patch("src.platform.leave_quota_service.run_realtime_leave_sync", return_value={"processed": 1}) as run_sync:
        result = admin_run_leave_realtime_sync(request, platform="wecom")
    assert result["processed"] == 1
    run_sync.assert_called_once_with(platform="wecom")

    req = LeavePolicyRequest(vacation_id=9, vacation_name="调休", leave_kind="comp_time", advance_seconds=259200)
    with patch("src.web.dashboard.require_console_context_from_request", return_value=admin_context), \
         patch("src.platform.leave_quota_service.configure_leave_policy", return_value={"vacation_id": 9}) as configure:
        result = admin_configure_leave_policy(req, request)
    assert result["policy"]["vacation_id"] == 9
    assert configure.call_args.kwargs["platform"] == "wecom"

    with patch("src.web.dashboard.require_console_context_from_request", return_value=admin_context), \
         patch("src.platform.leave_quota_service.sync_leave_policies_from_wecom_config", return_value={"synced": 3}) as sync:
        result = admin_sync_leave_policies(request, platform="wecom")
    assert result["synced"] == 3
    sync.assert_called_once_with(platform="wecom")


def test_admin_hr_specialist_apis_require_admin_context() -> None:
    from src.web.dashboard import (
        HrSpecialistBatchRequest,
        HrSpecialistRequest,
        admin_batch_hr_specialists,
        admin_list_hr_specialists,
        admin_set_hr_specialist,
    )

    request = _request("/api/v1/admin/hr-specialists")
    admin_context = {"platform": "wecom", "user_id": "AdminUser"}

    with patch("src.web.dashboard.require_admin_context_from_request", return_value=admin_context), \
         patch("src.platform.hr_specialist_service.list_hr_specialists", return_value=[{"user_id": "UserA"}]) as listed:
        result = admin_list_hr_specialists(request, platform="wecom")
    assert result["specialists"][0]["user_id"] == "UserA"
    listed.assert_called_once_with(platform="wecom")

    with patch("src.web.dashboard.require_admin_context_from_request", return_value=admin_context), \
         patch("src.platform.hr_specialist_service.set_hr_specialist", return_value={"user_id": "UserA", "enabled": True}) as set_one:
        result = admin_set_hr_specialist(HrSpecialistRequest(user_id="UserA", enabled=True), request)
    assert result["specialist"]["enabled"] is True
    assert set_one.call_args.kwargs["granted_by"] == "AdminUser"

    with patch("src.web.dashboard.require_admin_context_from_request", return_value=admin_context), \
         patch("src.platform.hr_specialist_service.bulk_set_hr_specialists", return_value={"updated": 2}) as set_batch:
        result = admin_batch_hr_specialists(HrSpecialistBatchRequest(user_ids=["UserA", "UserB"], enabled=False), request)
    assert result["updated"] == 2
    assert set_batch.call_args.kwargs["enabled"] is False


def test_admin_console_exposes_hr_specialist_and_leave_admin_controls() -> None:
    from src.web.dashboard import admin_console_page

    request = _request("/admin/console")
    with patch("src.web.dashboard.require_admin_context_from_request", return_value={"platform": "wecom", "user_id": "AdminUser", "role": "admin"}):
        html = admin_console_page(request).body.decode("utf-8")

    assert "审批假期管理" in html
    assert "批量设为人事专员" in html
    assert "setHrSpecialist" in html
    assert "/api/v1/admin/hr-specialists" in html
    assert "调整员工假期额度" in html


def test_admin_mail_account_list_does_not_treat_auth_user_id_as_filter() -> None:
    from src.web.dashboard import admin_list_mail_accounts

    request = _request("/api/v1/admin/mail/accounts?platform=wecom&user_id=AdminUser&admin_token=token")

    with patch("src.web.dashboard.require_admin_context_from_request", return_value={"platform": "wecom", "user_id": "AdminUser"}), \
         patch("src.platform.mail_account_service.list_mail_accounts", return_value={"accounts": [{"user_id": "UserA"}]}) as list_accounts:
        result = admin_list_mail_accounts(request, platform="wecom")

    assert result["accounts"][0]["user_id"] == "UserA"
    list_accounts.assert_called_once_with(platform="wecom", user_id="")


def test_admin_mail_account_resolves_user_name_before_saving() -> None:
    from src.web.dashboard import MailAccountRequest, admin_save_mail_account

    request = _request("/api/v1/admin/mail/accounts")
    payload = MailAccountRequest(email_address="u@example.com", imap_host="pop.example.com", user_name="张三")
    with patch("src.web.dashboard.require_admin_context_from_request", return_value={"platform": "wecom", "user_id": "admin"}), \
         patch("src.web.dashboard._resolve_mail_user_id", return_value="wecom-user-3") as resolve, \
         patch("src.platform.mail_account_service.save_mail_account", return_value={"user_id": "wecom-user-3"}) as save:
        result = admin_save_mail_account(payload, request)

    assert result["account"]["user_id"] == "wecom-user-3"
    resolve.assert_called_once_with("wecom", "", "张三")
    assert save.call_args.args[0]["user_id"] == "wecom-user-3"


def test_admin_mail_account_test_resolves_user_name() -> None:
    from src.web.dashboard import MailAccountStatusRequest, admin_test_mail_account

    request = _request("/api/v1/admin/mail/accounts/test")
    with patch("src.web.dashboard.require_admin_context_from_request", return_value={"platform": "wecom", "user_id": "admin"}), \
         patch("src.web.dashboard._resolve_mail_user_id", return_value="wecom-user-3") as resolve, \
         patch("src.platform.mail_account_service.summarize_user_mailbox", return_value="当前 POP3 邮箱没有邮件。") as summarize:
        result = admin_test_mail_account(MailAccountStatusRequest(platform="wecom", user_name="张三"), request)

    assert result["ok"] is True
    resolve.assert_called_once_with("wecom", "", "张三")
    summarize.assert_called_once_with("wecom", "wecom-user-3", limit=3)


def test_admin_mail_account_infer_resolves_user_and_returns_defaults() -> None:
    from src.web.dashboard import MailAccountInferRequest, admin_infer_mail_account

    request = _request("/api/v1/admin/mail/accounts/infer")
    defaults = {
        "user_id": "wecom-user-3",
        "email_address": "zhang.san@example.com",
        "imap_host": "pop.example.com",
        "poll_interval_minutes": 1,
    }
    with patch("src.web.dashboard.require_admin_context_from_request", return_value={"platform": "wecom", "user_id": "admin"}), \
         patch("src.web.dashboard._resolve_mail_user_id", return_value="wecom-user-3") as resolve, \
         patch("src.platform.mail_account_service.infer_mail_account_defaults", return_value=defaults) as infer:
        result = admin_infer_mail_account(MailAccountInferRequest(platform="wecom", user_name="张三"), request)

    assert result["account"]["email_address"] == "zhang.san@example.com"
    assert result["account"]["poll_interval_minutes"] == 1
    resolve.assert_called_once_with("wecom", "", "张三")
    infer.assert_called_once_with(platform="wecom", user_id="wecom-user-3", email_address="")


def test_admin_mail_account_test_uses_single_account_when_account_id_present() -> None:
    from src.web.dashboard import MailAccountStatusRequest, admin_test_mail_account

    request = _request("/api/v1/admin/mail/accounts/test")
    account = {"account_id": "mail-1", "user_id": "UserA", "email_address": "bin.han@example.com"}
    with patch("src.web.dashboard.require_admin_context_from_request", return_value={"platform": "wecom", "user_id": "admin"}), \
         patch("src.platform.mail_account_service.get_mail_account_by_id", return_value=account) as get_account, \
         patch("src.platform.mail_account_service.summarize_mail_account", return_value="单邮箱未读统计") as summarize_one, \
         patch("src.platform.mail_account_service.summarize_user_mailbox") as summarize_all:
        result = admin_test_mail_account(MailAccountStatusRequest(platform="wecom", user_id="UserA", account_id="mail-1"), request)

    assert result["ok"] is True
    assert result["user_id"] == "UserA"
    assert result["account_source"] == "默认邮箱 <bin.han@example.com>"
    assert result["result"] == "单邮箱未读统计"
    get_account.assert_called_once_with("mail-1")
    summarize_one.assert_called_once_with("mail-1", limit=3)
    summarize_all.assert_not_called()


def test_admin_can_save_and_delete_user_assistant_profile() -> None:
    from src.web.dashboard import (
        AssistantProfileAdminRequest,
        admin_delete_user_assistant_profile,
        admin_save_user_assistant_profile,
    )

    request = _request("/api/v1/admin/users/assistant-profile")
    profile_payload = {"assistant_name": "小智", "user_call_name": "张总", "role_name": "通用助手", "role_id": "general"}
    with patch("src.web.dashboard.require_admin_context_from_request", return_value={"platform": "wecom", "user_id": "admin"}), \
         patch("src.platform.assistant_profile_service.save_assistant_profile", return_value=profile_payload) as save_profile, \
         patch("src.gateway.provider_outbound.send_platform_text", return_value=True) as send_text:
        result = admin_save_user_assistant_profile(
            AssistantProfileAdminRequest(platform="wecom", user_id="u1", assistant_name="小智", user_call_name="张总", role_id="general"),
            request,
        )

    assert result["profile"]["assistant_name"] == "小智"
    assert result["notify_status"] == "sent"
    save_profile.assert_called_once_with(platform="wecom", user_id="u1", assistant_name="小智", user_call_name="张总", role_id="general")
    send_text.assert_called_once()

    with patch("src.web.dashboard.require_admin_context_from_request", return_value={"platform": "wecom", "user_id": "admin"}), \
         patch("src.platform.assistant_profile_service.delete_assistant_profile", return_value={"deleted": True, "user_id": "u1"}) as delete_profile:
        deleted = admin_delete_user_assistant_profile("wecom", "u1", request)

    assert deleted["deleted"] is True
    delete_profile.assert_called_once_with(platform="wecom", user_id="u1")


def test_admin_mail_account_test_appends_diagnostic_when_single_account_fails() -> None:
    from src.web.dashboard import MailAccountStatusRequest, admin_test_mail_account

    request = _request("/api/v1/admin/mail/accounts/test")
    account = {"account_id": "mail-1", "user_id": "HaHaXiao", "email_address": "xiaolin.zhang@example.com"}
    with patch("src.web.dashboard.require_admin_context_from_request", return_value={"platform": "wecom", "user_id": "admin"}), \
         patch("src.platform.mail_account_service.get_mail_account_by_id", return_value=account), \
         patch("src.platform.mail_account_service.summarize_mail_account", return_value="POP3 邮箱读取失败：账号或密码/授权码不正确"), \
         patch("src.platform.mail_account_service.diagnose_mail_account_connection", return_value="诊断结果：请重新生成客户端授权码") as diagnose:
        result = admin_test_mail_account(MailAccountStatusRequest(platform="wecom", user_id="HaHaXiao", account_id="mail-1"), request)

    assert result["ok"] is False
    assert result["diagnostic"] == "诊断结果：请重新生成客户端授权码"
    assert "【连接诊断】" in result["result"]
    assert "重新生成客户端授权码" in result["result"]
    diagnose.assert_called_once_with("mail-1")


def test_admin_console_mail_list_uses_safe_indexed_row_binding() -> None:
    from src.web.dashboard import admin_console_page

    html = admin_console_page().body.decode("utf-8")

    assert "window.mailAccountRows = []" in html
    assert "applyMailAccountByIndex" in html
    assert "newMailAccount" in html
    assert "新增邮箱" in html
    assert "inferMailAccount" in html
    assert "自动匹配邮箱配置" in html
    assert 'id="mailPollInterval" type="number" value="1"' in html
    assert "onchange=\"loadMailAccounts()\"" in html
    assert "mailAccountTable" in html
    assert "class=\"mail-table\"" in html
    assert "row-actions" in html
    assert "mono-wrap" in html


def test_admin_entry_menu_uses_admin_context() -> None:
    from src.web.dashboard import admin_entry_menu

    request = _request("/api/v1/admin/entry-menu")
    fake_menu = {"platform": "wecom", "user_id": "u-admin", "items": [{"title": "管理员控制台"}]}

    with patch("src.web.dashboard.require_admin_context_from_request", return_value={"platform": "wecom", "user_id": "u-admin"}), \
         patch("src.gateway.entry_links.build_platform_entry_menu", return_value=fake_menu) as build_menu:
        result = admin_entry_menu(request)

    assert result["items"][0]["title"] == "管理员控制台"
    build_menu.assert_called_once_with("wecom", "u-admin", is_admin=True)


def test_user_entry_menu_uses_user_context() -> None:
    from src.web.dashboard import user_entry_menu

    request = _request("/api/v1/user/entry-menu")
    fake_menu = {"platform": "feishu", "user_id": "u1", "items": [{"title": "知识库管理"}]}

    with patch("src.web.dashboard.require_user_context_from_request", return_value={"platform": "feishu", "user_id": "u1"}), \
         patch("src.gateway.entry_links.build_platform_entry_menu", return_value=fake_menu) as build_menu:
        result = user_entry_menu(request)

    assert result["platform"] == "feishu"
    build_menu.assert_called_once_with("feishu", "u1", is_admin=False)


def test_admin_entry_payloads_uses_admin_context() -> None:
    from src.web.dashboard import admin_entry_payloads

    request = _request("/api/v1/admin/entry-payloads")
    fake_payloads = {"platform": "wecom", "text": "可用入口", "feishu_card": {}, "dingtalk_card": {}}

    with patch("src.web.dashboard.require_admin_context_from_request", return_value={"platform": "wecom", "user_id": "u-admin"}), \
         patch("src.gateway.entry_links.build_platform_entry_payloads", return_value=fake_payloads) as build_payloads:
        result = admin_entry_payloads(request)

    assert result["text"] == "可用入口"
    build_payloads.assert_called_once_with("wecom", "u-admin", is_admin=True)


def test_user_entry_payloads_uses_user_context() -> None:
    from src.web.dashboard import user_entry_payloads

    request = _request("/api/v1/user/entry-payloads")
    fake_payloads = {"platform": "dingtalk", "text": "可用入口", "feishu_card": {}, "dingtalk_card": {}}

    with patch("src.web.dashboard.require_user_context_from_request", return_value={"platform": "dingtalk", "user_id": "u1"}), \
         patch("src.gateway.entry_links.build_platform_entry_payloads", return_value=fake_payloads) as build_payloads:
        result = user_entry_payloads(request)

    assert result["platform"] == "dingtalk"
    build_payloads.assert_called_once_with("dingtalk", "u1", is_admin=False)


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

    assert "--accent:#0078d4" in html
    assert "员工助手快速开通" in html
    assert "用户与权限管理" in html
    assert "nav-group" in html
    assert "filterAdminNav" in html
    assert "员工侧只看到一个助手" in html
    assert "用户管理" in html
    assert "模型管理" in html
    assert "工具与集成中心" in html
    assert "/api/v1/admin/integrations" in html
    assert "/api/v1/admin/integrations/test" in html
    assert "loadIntegrations" in html
    assert "testIntegration" in html
    assert "组织通知" in html
    assert "broadcastOrganization" in html
    assert "/api/v1/admin/organization/broadcast" in html
    assert "batchSetSelectedUsers" in html
    assert "discoverModels" in html
    assert "单次最大输出 Token（本地上限）" in html
    assert "不是服务商自动同步回来的上下文大小" in html
    assert "chooseModel(${jsAttr(model.id)},${jsAttr(model.name || model.id)})" in html
    assert "function modelProfileSlug(modelId)" in html
    assert "function setDefaultModel(profileId)" in html
    assert "function testModelProfile(profileId)" in html
    assert "function deleteModelProfile(profileId)" in html
    assert "function applyProfileToForm(profileId, provider, sdkFormat, apiBase, modelName, maxTokens)" in html
    assert "<button class=\"tonal\" onclick=\"setDefaultModel(${jsAttr(profile.profile_id)})\">默认</button>" in html
    assert "<button class=\"secondary\" onclick=\"testModelProfile(${jsAttr(profile.profile_id)})\">测试</button>" in html
    assert "<button class=\"danger\" onclick=\"deleteModelProfile(${jsAttr(profile.profile_id)})\">删除</button>" in html
    assert "applyProfileToForm(${jsAttr(profile.profile_id)},${jsAttr(profile.provider)}" in html
    assert "开通并通知员工" in html
    assert "知识范围和操作权限由平台根据员工在企业 IM 中的组织架构" in html
    assert "employeeScope" not in html
    assert "employeePermissions" not in html
    assert "确认自动接管企业微信" in html
    assert "高级配置：仅在系统提示缺少凭据时填写" in html
    assert "文档/待办能力" in html
    assert "企业 AI 助手文档能力" in html
    assert "企业 AI 助手待办能力" in html
    assert "后台自动协同应用通知、Bot 前台、群聊 @、文档/待办 MCP" in html
    assert "saveWecomMcpConfig" in html
    assert "mailAccounts" in html
    assert "/api/v1/admin/mail/accounts" in html
    assert "saveMailAccount" in html
    assert "testMailAccount" in html
    assert "deleteMailAccount" in html
    assert "phase1Readiness" in html
    assert "/api/v1/admin/phase1/readiness" in html
    assert "loadPhase1Readiness" in html
    assert "rateminChannelStatus" in html
    assert "/api/v1/admin/ratemin/channel-status" in html
    assert "/api/v1/admin/ratemin/recover" in html
    assert "recoverRateminChannel" in html


def test_knowledge_management_page_contains_business_operations() -> None:
    from src.web.dashboard import knowledge_management_page

    html = knowledge_management_page().body.decode("utf-8")

    assert "--accent:#0078d4" in html
    assert "新增到知识库" in html
    assert "上传文档入库" in html
    assert "scopeTree" in html
    assert "uploadKnowledgeFiles" in html
    assert "deleteEntryById(" in html
    assert "确认删除知识条目" in html
    assert "transferEntry('copy')" in html
    assert "transferEntry('cut')" in html
    assert "transferTarget" in html
    assert "renderScopeGroups" in html
    assert "升级知识条目" in html
    assert "导入公司级说明书文档" in html
    assert "按企业 IM 组织权限自动适配" in html


def test_knowledge_management_page_escapes_dynamic_values() -> None:
    from src.web.dashboard import knowledge_management_page

    html = knowledge_management_page().body.decode("utf-8")

    assert "function val(id)" in html
    assert "function safe(value)" in html
    assert "function jsString(value)" in html
    assert "function jsAttr(value)" in html
    assert 'onclick="filterByScope(${jsAttr(key)})"' in html
    assert 'data-scope-key="${safe(key)}"' in html
    assert "n.innerHTML.includes(key)" not in html
    assert "${safe(scopeLabel(scope))}" in html
    assert "${safe(item.title || item.id)}" in html
    assert "${safe(item.owner_id)}" in html
    assert "${safe(r.filename || r.id)}" in html
    assert "${safe(tags)}" in html
    assert "sel.innerHTML += `<option" not in html


def test_admin_and_knowledge_page_scripts_are_valid_javascript(tmp_path) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")

    from src.web.dashboard import admin_console_page, knowledge_management_page

    for name, response in {
        "admin-console": admin_console_page(),
        "knowledge-management": knowledge_management_page(),
    }.items():
        html = response.body.decode("utf-8")
        scripts = re.findall(r"<script>(.*?)</script>", html, flags=re.DOTALL)
        assert scripts
        for index, body in enumerate(scripts):
            assert "\x00" not in body
            script = tmp_path / f"{name}-{index}.js"
            script.write_text(body, encoding="utf-8")
            subprocess.run([node, "--check", str(script)], check=True)


def test_admin_console_dynamic_actions_use_js_string_arguments() -> None:
    from src.web.dashboard import admin_console_page

    html = admin_console_page().body.decode("utf-8")

    assert "function jsString(value)" in html
    assert "function jsAttr(value)" in html
    assert "editEmployeeNameFix(${jsAttr(assignment.platform)},${jsAttr(assignment.user_id)},${jsAttr(fixedName)})" in html
    assert "setOneUserBot(${jsAttr(user.user_id)},'active')" in html
    assert "openUserAssistantProfileEditor(${jsAttr(user.user_id)}" in html
    assert "function saveUserAssistantProfileFromEditor()" in html
    assert 'id="profileUserCallName"' in html
    assert 'id="profileRoleId"' in html
    assert "deleteUserAssistantProfile(${jsAttr(user.user_id)})" in html
    assert "chooseModel(${jsAttr(model.id)},${jsAttr(model.name || model.id)})" in html
    assert "selectEmployee(${jsAttr(u.user_id)},${jsAttr(u.name||u.user_id)})" in html
    assert "editEmployeeNameFix(\\'" not in html


def test_admin_console_identity_legacy_scripts_do_not_inject_profile_html() -> None:
    from src.web.dashboard import admin_console_page

    html = admin_console_page().body.decode("utf-8")

    assert "identity.innerHTML = (profile.platform || platform)" not in html
    assert "profileBox.innerHTML = '<span class=\"chip ok\">用户：' + (profile.user_id || userId)" not in html
    assert "identity.textContent = (profile.platform || platform)" in html
    assert "profileBox.textContent = '用户：' + (profile.user_id || userId) + ' / 角色：' + (profile.role || 'admin')" in html


def test_admin_console_employee_bots_load_users_before_rendering() -> None:
    from src.web.dashboard import admin_console_page

    html = admin_console_page().body.decode("utf-8")
    init_match = re.search(r"\(async function init\(\).*?\}\)\(\);", html, flags=re.DOTALL)
    assert init_match
    init_script = init_match.group(0)

    assert "async function ensureAdminUsersLoaded()" in html
    assert "await ensureAdminUsersLoaded();" in html
    assert init_script.index("await loadAdminUsers(false);") < init_script.index("await loadEmployeeBots();")
    assert "window.allUsers.forEach(u => { nameMap[u.user_id] = u.name || ''; });" in html
    assert "const employeeMain = empName || assignment.user_id;" in html
    assert "const accountLine = empName && empName !== assignment.user_id ?" in html


def test_admin_console_employee_bot_default_name_is_not_marked_damaged() -> None:
    from src.web.dashboard import admin_console_page

    html = admin_console_page().body.decode("utf-8")

    assert "function isDamagedDisplayName(value)" in html
    assert "if (!text) return false;" in html
    assert "function defaultEmployeeBotName(platform)" in html
    assert "const isGarbled = isDamagedDisplayName(rawDisplayName);" in html
    assert "const fixedName = rawDisplayName && !isGarbled ? rawDisplayName : defaultEmployeeBotName(assignment.platform);" in html
    assert "displayName.length < 3" not in html


def test_admin_console_employee_bot_welcome_action_is_available() -> None:
    from src.web.dashboard import admin_console_page

    html = admin_console_page().body.decode("utf-8")

    assert "async function sendEmployeeWelcome(platform, userId, displayName)" in html
    assert "/api/v1/admin/employee-bots/welcome" in html
    assert "重发欢迎" in html
    assert "el('employeeBotName').value = defaultEmployeeBotName(val('employeePlatform') || 'wecom');" in html
    assert "el('employeeBotName').value = name;" not in html


def test_admin_console_navigation_uses_stable_tab_ids_and_safe_fallback() -> None:
    from src.web.dashboard import admin_console_page

    html = admin_console_page().body.decode("utf-8")

    assert 'data-tab="leaveAdmin"' in html
    assert 'document.querySelector(`nav button[data-tab="${id}"]`)' in html
    assert "if (navButton) navButton.classList.add('active');" in html
    assert "nav button[data-tab=&quot;leaveAdmin&quot;]" in html
    assert "onclick*=\\\\'leaveAdmin" not in html


def test_admin_console_leave_admin_supports_department_batch_selection() -> None:
    from src.web.dashboard import admin_console_page

    html = admin_console_page().body.decode("utf-8")

    assert "按部门选择员工" in html
    assert "id=\"leaveUserDirectory\"" in html
    assert "selectFilteredLeaveUsers(true)" in html
    assert "async function loadLeaveUserDirectory" in html
    assert "function renderLeaveUserDirectory" in html
    assert "async function applyLeaveBalanceTargetBatch" in html
    assert "/api/v1/admin/leave/balance-target/batch" in html
    assert "员工姓名或用户 ID" in html


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


def test_create_knowledge_user_link_includes_signed_user_token() -> None:
    from scripts.create_knowledge_user_link import build_knowledge_user_link

    with patch.dict("os.environ", {"ANT_COLONY_ADMIN_SESSION_SECRET": "secret"}, clear=False):
        link = build_knowledge_user_link(
            base_url="http://example.test",
            platform="wecom",
            user_id="u-employee",
            ttl_seconds=60,
        )

    assert link.startswith("http://example.test/knowledge/user?")
    assert "platform=wecom" in link
    assert "user_id=u-employee" in link
    assert "user_token=" in link
