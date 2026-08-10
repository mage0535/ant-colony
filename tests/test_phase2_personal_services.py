from __future__ import annotations

import sqlite3
from unittest.mock import patch


def _reset_db(db_path: str) -> None:
    from src.store.database import Database

    Database.get(db_path).close()
    Database._instances.pop(db_path, None)  # type: ignore[attr-defined]


def test_assistant_profile_persists_name_and_role_and_onboarding_is_once(tmp_path) -> None:
    from src.platform.assistant_profile_service import get_or_create_onboarding, save_assistant_profile

    db_path = str(tmp_path / "assistant-profile.db")
    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False):
        _reset_db(db_path)
        first = get_or_create_onboarding(platform="wecom", user_id="u1", user_name="张三")
        saved = save_assistant_profile(
            platform="wecom",
            user_id="u1",
            assistant_name="小智",
            user_call_name="张工",
            role_id="document_specialist",
        )
        second = get_or_create_onboarding(platform="wecom", user_id="u1", user_name="张三")

    assert first["is_first_conversation"] is True
    assert "角色" in first["message"]
    assert "起名" in first["message"]
    assert saved["assistant_name"] == "小智"
    assert saved["user_call_name"] == "张工"
    assert saved["role_id"] == "document_specialist"
    assert second["is_first_conversation"] is False
    assert second["assistant_name"] == "小智"
    assert second["user_call_name"] == "张工"


def test_assistant_profile_onboarding_retries_when_database_is_locked() -> None:
    from src.platform.assistant_profile_service import get_or_create_onboarding

    class FakeCursor:
        rowcount = 1

    class FakeConn:
        def __init__(self) -> None:
            self.insert_attempts = 0
            self.commits = 0
            self.rollbacks = 0

        def execute(self, sql, _params=()):
            if sql.strip().upper().startswith("SELECT"):
                return self
            if "INSERT OR IGNORE INTO assistant_user_profiles" in sql:
                self.insert_attempts += 1
                if self.insert_attempts == 1:
                    raise sqlite3.OperationalError("database is locked")
                return FakeCursor()
            return FakeCursor()

        def fetchone(self):
            return None

        def commit(self):
            self.commits += 1

        def rollback(self):
            self.rollbacks += 1

    fake = FakeConn()

    with patch("src.platform.assistant_profile_service._conn", return_value=fake), \
         patch("src.platform.assistant_profile_service.time.sleep", return_value=None):
        result = get_or_create_onboarding(platform="wecom", user_id="u1", user_name="User")

    assert result["is_first_conversation"] is True
    assert fake.insert_attempts == 2
    assert fake.rollbacks == 1
    assert fake.commits == 1


def test_assistant_profile_extracts_user_call_name_and_can_delete(tmp_path) -> None:
    from src.platform.assistant_profile_service import (
        delete_assistant_profile,
        extract_profile_request,
        get_assistant_profile,
        save_assistant_profile,
    )

    db_path = str(tmp_path / "assistant-profile-call-name.db")
    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False):
        _reset_db(db_path)
        parsed = extract_profile_request("你的名字叫小智，以后叫我张工，角色选文档与制度顾问")
        saved = save_assistant_profile(platform="wecom", user_id="u1", **parsed)
        deleted = delete_assistant_profile(platform="wecom", user_id="u1")
        profile_after_delete = get_assistant_profile(platform="wecom", user_id="u1")

    assert parsed["assistant_name"] == "小智"
    assert parsed["user_call_name"] == "张工"
    assert saved["user_call_name"] == "张工"
    assert deleted["deleted"] is True
    assert profile_after_delete is None


def test_assistant_profile_update_message_explains_frontend_effect(tmp_path) -> None:
    from src.platform.assistant_profile_service import build_profile_update_notice, save_assistant_profile

    db_path = str(tmp_path / "assistant-profile-update-notice.db")
    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False):
        _reset_db(db_path)
        profile = save_assistant_profile(
            platform="wecom",
            user_id="u1",
            assistant_name="小智",
            user_call_name="张工",
            role_id="document_specialist",
        )
        notice = build_profile_update_notice(profile)

    assert "小智" in notice
    assert "张工" in notice
    assert "文档与制度顾问" in notice
    assert "企业微信会话顶部显示的应用或机器人名称可能仍是统一名称" in notice
    assert "你可以问我“你叫什么”" in notice


def test_personal_agent_answers_profile_status_from_saved_profile(tmp_path) -> None:
    from src.agents.personal_agent import PersonalAgent
    from src.models.contracts import MessageContext, SpaceType
    from src.platform.assistant_profile_service import save_assistant_profile

    class DummyEngine:
        def process_text(self, *args, **kwargs):
            raise AssertionError("profile status query should not call LLM")

    db_path = str(tmp_path / "assistant-profile-status-query.db")
    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False):
        _reset_db(db_path)
        save_assistant_profile(
            platform="wecom",
            user_id="u1",
            assistant_name="小智",
            user_call_name="张工",
            role_id="document_specialist",
        )
        agent = PersonalAgent("u1", DummyEngine())  # type: ignore[arg-type]
        context = MessageContext(space_type=SpaceType.DEPARTMENT, space_id="dept-1", metadata={"provider": "wecom"})
        response = agent.process_message("u1", "你叫什么，当前是什么角色？", context)

    assert "小智" in response.text
    assert "张工" in response.text
    assert "文档与制度顾问" in response.text
    assert "企业微信会话顶部显示的应用或机器人名称可能仍是统一名称" in response.text


def test_daily_brief_notifies_active_user_once_per_day(tmp_path) -> None:
    from src.platform.daily_brief_service import run_daily_briefs
    from src.platform.employee_bot_service import activate_employee_bot

    db_path = str(tmp_path / "daily-brief.db")
    sent: list[tuple[str, str, str]] = []
    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False), \
         patch("src.platform.employee_bot_service._derive_employee_access", return_value={
             "role": "self", "default_scope": "personal:u1", "readable_scopes": [],
             "writable_scopes": [], "permissions": ["chat.use"],
         }), \
         patch("src.platform.daily_brief_service._build_brief", return_value="【今日工作简报】\n今日暂无待办。"), \
         patch("src.platform.daily_brief_service.provider_outbound.send_platform_text", side_effect=lambda p, u, t: sent.append((p, u, t)) or True):
        _reset_db(db_path)
        activate_employee_bot(platform="wecom", user_id="u1", notify=False)
        first = run_daily_briefs("wecom")
        second = run_daily_briefs("wecom")

    assert first["notified"] == 1
    assert second["skipped"] == 1
    assert sent == [("wecom", "u1", "【今日工作简报】\n今日暂无待办。")]


def test_daily_brief_includes_real_leave_and_attendance_anomalies_only() -> None:
    from src.platform.daily_brief_service import _build_brief

    with patch("src.platform.daily_brief_service.invoke_capability", return_value=""), \
         patch("src.tools.task_tools.query_tasks_tool", return_value=""), \
         patch("src.tools.attendance_tool.query_leave_balance", return_value="假期余额明细（来自企业微信）：\n年假：剩余 3 天"), \
         patch("src.tools.attendance_tool.query_attendance", return_value="考勤记录：\n2026-07-17：迟到"):
        brief = _build_brief("wecom", "u1")

    assert "假期余额" in brief
    assert "考勤提醒" in brief
    assert "迟到" in brief
