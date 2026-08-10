from __future__ import annotations

from unittest.mock import patch


def _reset_db(db_path: str) -> None:
    from src.store.database import Database

    Database.get(db_path).close()
    Database._instances.pop(db_path, None)  # type: ignore[attr-defined]


def _seed_directory(db_path: str) -> None:
    from src.platform.org_graph import OrgGraphService

    graph = OrgGraphService(db_path)
    graph.upsert_department("wecom", "1", "公司", "")
    graph.upsert_department("wecom", "2", "技术部", "1")
    graph.upsert_department("wecom", "3", "后端组", "2")
    graph.upsert_department("wecom", "4", "财务部", "1")
    graph.upsert_user("wecom", "u-admin", "管理员")
    graph.upsert_user("wecom", "u-tech", "技术员工")
    graph.upsert_user("wecom", "u-child", "后端员工")
    graph.upsert_user("wecom", "u-finance", "财务员工")
    graph.upsert_user("wecom", "u-paused", "暂停员工")
    graph.replace_user_memberships("wecom", "u-admin", [("1", False, True)])
    graph.replace_user_memberships("wecom", "u-tech", [("2", False, False)])
    graph.replace_user_memberships("wecom", "u-child", [("3", False, False)])
    graph.replace_user_memberships("wecom", "u-finance", [("4", False, False)])
    graph.replace_user_memberships("wecom", "u-paused", [("2", False, False)])


def _activate_users() -> None:
    from src.platform.employee_bot_service import activate_employee_bot, pause_employee_bot

    for user_id in ["u-tech", "u-child", "u-finance", "u-paused"]:
        activate_employee_bot(platform="wecom", user_id=user_id, notify=False)
    pause_employee_bot(platform="wecom", user_id="u-paused", updated_by="u-admin")


def test_broadcast_to_all_employees_sends_only_active_ai_assistants(tmp_path) -> None:
    from src.platform.organization_broadcast_service import broadcast_to_organization

    db_path = str(tmp_path / "org-broadcast-all.db")
    sent: list[tuple[str, str, str]] = []

    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False), \
         patch("src.platform.employee_bot_service._derive_employee_access", return_value={
             "role": "self",
             "default_scope": "personal:any",
             "readable_scopes": ["personal:any"],
             "writable_scopes": ["personal:any"],
             "permissions": ["chat.use"],
         }), \
         patch("src.gateway.provider_outbound.send_platform_text", side_effect=lambda platform, user_id, text: sent.append((platform, user_id, text)) or True):
        _reset_db(db_path)
        _seed_directory(db_path)
        _activate_users()
        result = broadcast_to_organization(
            platform="wecom",
            sender_user_id="u-admin",
            target="全体员工",
            message="注意天气",
        )

    assert result["ok"] is True
    assert result["target"]["type"] == "organization"
    assert result["sent"] == 3
    assert result["skipped"] == 1
    assert [item[1] for item in sent] == ["u-child", "u-finance", "u-tech"]
    assert {item[2] for item in sent} == {"注意天气"}


def test_broadcast_to_department_matches_name_and_child_departments(tmp_path) -> None:
    from src.platform.organization_broadcast_service import broadcast_to_organization

    db_path = str(tmp_path / "org-broadcast-department.db")
    sent: list[str] = []

    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False), \
         patch("src.platform.employee_bot_service._derive_employee_access", return_value={
             "role": "self",
             "default_scope": "personal:any",
             "readable_scopes": ["personal:any"],
             "writable_scopes": ["personal:any"],
             "permissions": ["chat.use"],
         }), \
         patch("src.gateway.provider_outbound.send_platform_text", side_effect=lambda _platform, user_id, _text: sent.append(user_id) or True):
        _reset_db(db_path)
        _seed_directory(db_path)
        _activate_users()
        result = broadcast_to_organization(
            platform="wecom",
            sender_user_id="u-admin",
            target="技术部",
            message="下班关灯",
        )

    assert result["ok"] is True
    assert result["target"] == {"type": "department", "id": "2", "name": "技术部"}
    assert result["sent"] == 2
    assert result["skipped"] == 1
    assert sent == ["u-child", "u-tech"]


def test_broadcast_tool_rejects_non_admin_user() -> None:
    from src.tools.builtin import _broadcast_org_message_tool

    with patch("src.web.admin_auth.is_platform_admin", return_value=False):
        result = _broadcast_org_message_tool(
            {
                "platform": "wecom",
                "user_id": "u-employee",
                "target": "全体员工",
                "message": "注意天气",
            }
        )

    assert result == "你当前没有管理员权限，不能向组织架构群发通知。"
