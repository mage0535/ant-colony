from __future__ import annotations

from unittest.mock import patch


def test_user_management_merges_org_users_bot_status_and_usage(tmp_path, monkeypatch) -> None:
    from src.store.database import Database

    db_path = tmp_path / "ant-colony.db"
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(db_path))
    Database._instances.clear()
    graph = __import__("src.platform.org_graph", fromlist=["OrgGraphService"]).OrgGraphService(str(db_path))
    graph.upsert_department("wecom", "1", "总经办", "")
    graph.upsert_user("wecom", "u1", "张三")
    graph.replace_user_memberships("wecom", "u1", [("1", False, True)])

    from src.platform.employee_bot_service import activate_employee_bot
    from src.platform.user_management_service import list_admin_user_details

    with patch("src.platform.employee_bot_service._notify_employee", return_value="sent"):
        activate_employee_bot(platform="wecom", user_id="u1", display_name="企业 AI 助手", notify=True)

    result = list_admin_user_details("wecom", sync=False)

    assert result["users"][0]["user_id"] == "u1"
    assert result["users"][0]["bot_status"] == "active"
    assert result["users"][0]["is_admin"] is True


def test_model_discovery_without_key_returns_actionable_message() -> None:
    from src.platform.model_management_service import discover_models

    result = discover_models({"provider": "openai", "api_key": ""})

    assert result["ok"] is False
    assert "API Key" in result["message"]
