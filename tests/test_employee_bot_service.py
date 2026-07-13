from __future__ import annotations

from unittest.mock import patch


def test_activate_employee_bot_records_assignment_and_sends_wecom_notice(tmp_path) -> None:
    from src.platform.employee_bot_service import activate_employee_bot, list_employee_bot_assignments
    from src.store.database import Database

    db_path = str(tmp_path / "employee-bot.db")
    derived_access = {
        "role": "leader",
        "default_scope": "department:dept-2",
        "readable_scopes": ["personal:u-employee", "organization:*", "department:dept-2"],
        "writable_scopes": ["personal:u-employee", "department:dept-2"],
        "permissions": ["chat.use", "files.process", "knowledge.read", "knowledge.write"],
    }
    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False), \
         patch("src.platform.employee_bot_service._notify_employee", return_value="sent"), \
         patch("src.platform.employee_bot_service._derive_employee_access", return_value=derived_access):
        Database.get(db_path).close()
        Database._instances.pop(db_path, None)  # type: ignore[attr-defined]
        result = activate_employee_bot(
            platform="wecom",
            user_id="u-employee",
            display_name="企业 AI 助手",
            scope="organization",
            permissions=["manual.permission"],
            activated_by="u-admin",
        )
        assignments = list_employee_bot_assignments("wecom")

    assert result["status"] == "active"
    assert result["notify_status"] == "sent"
    assert result["scope"] == "department:dept-2"
    assert result["permissions"] == ["chat.use", "files.process", "knowledge.read", "knowledge.write"]
    assert assignments[0]["user_id"] == "u-employee"
    assert assignments[0]["scope"] == "department:dept-2"


def test_send_employee_bot_welcome_updates_notify_status_and_intro_message(tmp_path) -> None:
    from src.platform.employee_bot_service import activate_employee_bot, send_employee_bot_welcome
    from src.store.database import Database

    db_path = str(tmp_path / "employee-bot-welcome.db")
    sent_messages: list[tuple[str, str]] = []

    def fake_send_text(user_id: str, content: str) -> bool:
        sent_messages.append((user_id, content))
        return True

    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False), \
         patch("src.gateway.wecom_outbound.send_text", side_effect=fake_send_text), \
         patch("src.platform.employee_bot_service._derive_employee_access", return_value={
             "role": "self",
             "default_scope": "personal:u-employee",
             "readable_scopes": ["personal:u-employee"],
             "writable_scopes": ["personal:u-employee"],
             "permissions": ["chat.use", "files.process", "knowledge.read", "knowledge.write"],
         }):
        Database.get(db_path).close()
        Database._instances.pop(db_path, None)  # type: ignore[attr-defined]
        activate_employee_bot(platform="wecom", user_id="u-employee", notify=False)
        result = send_employee_bot_welcome(platform="wecom", user_id="u-employee", display_name="企业 AI 助手")

    assert result["notify_status"] == "sent"
    assert result["assignment"]["notify_status"] == "sent"
    assert sent_messages
    assert sent_messages[-1][0] == "u-employee"
    assert "你的企业 AI 助手已开通：企业 AI 助手" in sent_messages[-1][1]
    assert "直接在这条消息所在会话里回复“你好”" in sent_messages[-1][1]
    assert "查询公司知识库" in sent_messages[-1][1]


def test_deactivate_employee_bot_marks_assignment_disabled(tmp_path) -> None:
    from src.platform.employee_bot_service import activate_employee_bot, deactivate_employee_bot
    from src.store.database import Database

    db_path = str(tmp_path / "employee-bot-disable.db")
    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False), \
         patch("src.platform.employee_bot_service._notify_employee", return_value="sent"):
        Database.get(db_path).close()
        Database._instances.pop(db_path, None)  # type: ignore[attr-defined]
        activate_employee_bot(platform="wecom", user_id="u-employee")
        result = deactivate_employee_bot(platform="wecom", user_id="u-employee", updated_by="u-admin")

    assert result["status"] == "disabled"
    assert result["activated_by"] == "u-admin"


def test_list_employee_bot_assignments_repairs_legacy_damaged_display_name(tmp_path) -> None:
    from src.platform.employee_bot_service import activate_employee_bot, list_employee_bot_assignments
    from src.store.database import Database

    db_path = str(tmp_path / "employee-bot-repair.db")
    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False), \
         patch("src.platform.employee_bot_service._notify_employee", return_value="sent"):
        Database.get(db_path).close()
        Database._instances.pop(db_path, None)  # type: ignore[attr-defined]
        activate_employee_bot(platform="wecom", user_id="u-employee", display_name="企业 AI 助手")
        conn = Database.get(db_path).connect()
        conn.execute(
            "UPDATE employee_bot_assignments SET display_name = ? WHERE platform = ? AND user_id = ?",
            ("?? AI ??", "wecom", "u-employee"),
        )
        conn.commit()

        assignments = list_employee_bot_assignments("wecom")
        stored_name = conn.execute(
            "SELECT display_name FROM employee_bot_assignments WHERE platform = ? AND user_id = ?",
            ("wecom", "u-employee"),
        ).fetchone()[0]

    assert assignments[0]["display_name"] == "企业 AI 助手"
    assert stored_name == "企业 AI 助手"
