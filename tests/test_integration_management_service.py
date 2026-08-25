from __future__ import annotations

from unittest.mock import patch


def test_integration_center_aggregates_core_modules() -> None:
    from src.platform.integration_management_service import list_integrations

    with patch("src.platform.activation_service.list_platform_bot_statuses", return_value=[
        {"platform": "wecom", "platform_label": "企业微信", "enabled": True, "missing_keys": [], "configured_keys": ["bot_id"], "next_action": "可用"}
    ]), patch("src.platform.phase1_readiness_service.collect_phase1_readiness", return_value={
        "items": {
            "contacts": {"name": "通讯录搜索", "status": "ready", "summary": "已同步", "metrics": {}},
            "approval": {"name": "审批/流程", "status": "needs_config", "summary": "缺少权限", "metrics": {}},
        }
    }), patch("src.platform.model_management_service.list_model_profiles", return_value={
        "profiles": [{"profile_id": "default", "model_name": "gpt-test", "enabled": True, "api_key_configured": True, "is_default": True}]
    }), patch("src.platform.mail_account_service.list_mail_accounts", return_value={
        "accounts": [{"enabled": True, "password_configured": True}]
    }), patch("src.knowledge.repository_factory.build_knowledge_repository") as repo_factory, patch(
        "src.platform.ratemin_collector_health.get_ratemin_channel_status",
        return_value={"overall_status": "healthy", "problem_origin": "none", "project_server": {"summary": "正常"}},
    ), patch("src.platform.wecom_robot_mcp_provider.get_wecom_robot_mcp_status", return_value={
        "doc": {"label": "文档", "configured": True, "tools": ["create_doc"]},
        "todo": {"label": "待办", "configured": False},
    }), patch("src.platform.public_data_service.list_data_source_configs", return_value=[
        {"kind": "weather", "label": "天气", "source": "Open-Meteo", "builtin": True, "configured": False},
        {"kind": "flight", "label": "航班", "source": "API", "builtin": False, "configured": False},
    ]):
        repo_factory.return_value.list_accessible.return_value = [object()]
        result = list_integrations(platform="wecom", user_id="u-admin")

    ids = {item["id"] for item in result["items"]}
    assert "platform:wecom" in ids
    assert "enterprise_app:contacts" in ids
    assert "enterprise_app:approval" in ids
    assert "models:profiles" in ids
    assert "mail:accounts" in ids
    assert "knowledge:accessible" in ids
    assert "ratemin:channel" in ids
    assert "wecom_mcp:doc_todo" in ids
    assert "public_data:weather" in ids
    assert "public_data:flight" in ids
    assert any(item["category"] == "联网搜索源" for item in result["items"])
    assert result["summary"]["total"] == len(result["items"])


def test_integration_center_tests_public_data_source() -> None:
    from src.platform.integration_management_service import test_integration

    with patch("src.platform.public_data_service.test_data_source", return_value={"ok": True, "result": "北京天气正常"}):
        result = test_integration("public_data:weather", query="北京天气")

    assert result["ok"] is True
    assert result["status"] == "ready"
    assert "北京天气正常" in result["result"]


def test_integration_center_keeps_page_available_when_one_module_fails() -> None:
    from src.platform.integration_management_service import list_integrations

    with patch("src.platform.activation_service.list_platform_bot_statuses", side_effect=SystemError("sqlite edge")), patch(
        "src.platform.phase1_readiness_service.collect_phase1_readiness", return_value={"items": {}}
    ), patch("src.platform.model_management_service.list_model_profiles", return_value={"profiles": []}), patch(
        "src.platform.mail_account_service.list_mail_accounts", return_value={"accounts": []}
    ), patch("src.knowledge.repository_factory.build_knowledge_repository") as repo_factory, patch(
        "src.platform.ratemin_collector_health.get_ratemin_channel_status", return_value={"overall_status": "healthy"}
    ), patch("src.platform.wecom_robot_mcp_provider.get_wecom_robot_mcp_status", return_value={}), patch(
        "src.platform.public_data_service.list_data_source_configs", return_value=[]
    ):
        repo_factory.return_value.list_accessible.return_value = []
        result = list_integrations(platform="wecom", user_id="u-admin")

    error_item = next(item for item in result["items"] if item["id"] == "system:platform")
    assert error_item["status"] == "error"
    assert "sqlite edge" in error_item["summary"]
    assert result["summary"]["total"] >= 1
