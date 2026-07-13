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


def test_admin_user_details_api_requires_admin_context() -> None:
    from src.web.dashboard import admin_user_details

    request = _request("/api/v1/admin/users")
    fake = {"platform": "wecom", "users": [{"user_id": "u2", "bot_status": "active"}]}
    with patch("src.web.dashboard.require_admin_context_from_request", return_value={"platform": "wecom", "user_id": "u-admin"}), \
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


def test_admin_model_management_apis() -> None:
    from src.web.dashboard import ModelDiscoverRequest, ModelProfileRequest, admin_discover_models, admin_model_profiles, admin_save_model_profile

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
    assert "员工 AI 助手" in html
    assert "用户管理" in html
    assert "模型管理" in html
    assert "batchSetSelectedUsers" in html
    assert "discoverModels" in html
    assert "开通并通知员工" in html
    assert "知识范围和操作权限由平台根据员工在企业 IM 中的组织架构" in html
    assert "employeeScope" not in html
    assert "employeePermissions" not in html
    assert "确认自动接管企业微信" in html
    assert "高级配置：仅在系统提示缺少凭据时填写" in html
    assert "企微 MCP" in html
    assert "企业微信文档 MCP" in html
    assert "企业微信待办 MCP" in html
    assert "saveWecomMcpConfig" in html


def test_knowledge_management_page_contains_business_operations() -> None:
    from src.web.dashboard import knowledge_management_page

    html = knowledge_management_page().body.decode("utf-8")

    assert "--accent:#0078d4" in html
    assert "新增到知识库" in html
    assert "上传文档入库" in html
    assert "scopeTree" in html
    assert "uploadKnowledgeFiles" in html
    assert "renderScopeGroups" in html
    assert "升级知识条目" in html
    assert "导入公司级说明书文档" in html
    assert "按企业 IM 组织权限自动适配" in html


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
    assert "chooseModel(${jsAttr(model.id)})" in html
    assert "selectEmployee(${jsAttr(u.user_id)},${jsAttr(u.name||u.user_id)})" in html
    assert "editEmployeeNameFix(\\'" not in html


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
