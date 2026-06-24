from __future__ import annotations

from unittest.mock import patch


def test_activate_employee_bot_records_assignment_and_sends_wecom_notice(tmp_path) -> None:
    from src.platform.employee_bot_service import activate_employee_bot, list_employee_bot_assignments
    from src.store.database import Database

    db_path = str(tmp_path / "employee-bot.db")
    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False), \
         patch("src.platform.employee_bot_service._notify_employee", return_value="sent"):
        Database.get(db_path).close()
        Database._instances.pop(db_path, None)  # type: ignore[attr-defined]
        result = activate_employee_bot(
            platform="wecom",
            user_id="u-employee",
            display_name="企业 AI 助手",
            scope="department",
            permissions=["chat.use", "knowledge.read"],
            activated_by="u-admin",
        )
        assignments = list_employee_bot_assignments("wecom")

    assert result["status"] == "active"
    assert result["notify_status"] == "sent"
    assert result["permissions"] == ["chat.use", "knowledge.read"]
    assert assignments[0]["user_id"] == "u-employee"


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
