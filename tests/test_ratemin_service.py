from __future__ import annotations

import sqlite3
from unittest.mock import patch


def _reset_db(db_path: str) -> None:
    from src.store.database import Database

    Database.get(db_path).close()
    Database._instances.pop(db_path, None)  # type: ignore[attr-defined]


def test_ratemin_current_sync_retries_when_database_is_locked(tmp_path) -> None:
    from src.platform import ratemin_service
    from src.platform.ratemin_service import sync_ratemin_current_events
    from src.store.database import Database

    db_path = str(tmp_path / "ratemin-current-retry.db")
    attempts = {"count": 0}
    original = ratemin_service._sync_current_events_once

    def flaky_once(*args, **kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise sqlite3.OperationalError("database is locked")
        return original(*args, **kwargs)

    event = {
        "source_db": "business_a",
        "flow_id": "215",
        "flow_post_id": "63948",
        "data_id": "1176191",
        "task_id": "405",
        "recipient_oper_id": "309",
        "recipient_name": "张三",
        "subject": "测试流程",
        "content": "请尽快处理",
    }
    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False), \
         patch("src.platform.ratemin_service._sync_current_events_once", side_effect=flaky_once), \
         patch("src.platform.ratemin_service.time.sleep", return_value=None):
        _reset_db(db_path)
        Database.get(db_path).connect()
        result = sync_ratemin_current_events([event], source_databases=["business_a"])

    assert attempts["count"] == 2
    assert result["active"] == 1


def test_ratemin_ingest_auto_matches_by_display_name_and_notifies(tmp_path) -> None:
    from src.platform.employee_bot_service import activate_employee_bot
    from src.platform.ratemin_service import ingest_ratemin_events, query_my_ratemin_todos, sync_ratemin_current_events
    from src.store.database import Database

    db_path = str(tmp_path / "ratemin.db")
    sent: list[tuple[str, str, str]] = []
    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False), \
         patch("src.platform.employee_bot_service._derive_employee_access", return_value={
             "role": "self",
             "default_scope": "personal:u-zhang",
             "readable_scopes": ["personal:u-zhang"],
             "writable_scopes": ["personal:u-zhang"],
             "permissions": ["chat.use"],
         }), \
         patch("src.platform.ratemin_service.provider_outbound.send_platform_text", side_effect=lambda p, u, t: sent.append((p, u, t)) or True):
        _reset_db(db_path)
        conn = Database.get(db_path).connect()
        conn.execute("INSERT INTO org_users(platform,user_id,name) VALUES('wecom','u-zhang','员工甲')")
        conn.commit()
        activate_employee_bot(platform="wecom", user_id="u-zhang", display_name="企业 AI 助手", notify=False)

        event = {
                    "source_db": "business_a",
                    "flow_id": "215",
                    "flow_post_id": "63948",
                    "data_id": "1176191",
                    "task_id": "405",
                    "flow_name": "外购申请单",
                    "recipient_oper_id": "309",
                    "recipient_login_name": "ZHANG_Xiaolin",
                    "recipient_name": "员工甲_ZHANG Xiaolin",
                    "subject": "DY26008",
                    "content": "请尽快查阅",
                    "todo_time": "2026-07-15 08:01:56",
                    "initiator_name": "钱七_WEI Yongsen",
                }
        result = ingest_ratemin_events([event])
        sync_ratemin_current_events([event], source_databases=["business_a"])
        todos = query_my_ratemin_todos(platform="wecom", user_id="u-zhang", query="DY26008")

    assert result["inserted"] == 1
    assert result["notified"] == 1
    assert sent and sent[0][0] == "wecom" and sent[0][1] == "u-zhang"
    assert "[业务系统 business_a]" in sent[0][2]
    assert "收到时间" in sent[0][2]
    assert "流程发起人：钱七" in sent[0][2]
    assert todos["count"] == 1
    assert "DY26008" in todos["message"]


def test_ratemin_unmatched_event_waits_for_manual_binding(tmp_path) -> None:
    from src.platform.ratemin_service import bind_ratemin_user, ingest_ratemin_events, list_ratemin_bindings

    db_path = str(tmp_path / "ratemin-unmatched.db")
    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False):
        _reset_db(db_path)
        result = ingest_ratemin_events(
            [
                {
                    "source_db": "business_b",
                    "flow_id": "334",
                    "flow_post_id": "34759",
                    "data_id": "487061",
                    "task_id": "342",
                    "recipient_oper_id": "343",
                    "recipient_name": "技术部经理",
                    "subject": "RD2004JBSL",
                    "content": "请尽快查阅",
                }
            ]
        )
        binding = bind_ratemin_user(
            source_db="business_b",
            rate_oper_id="343",
            rate_display_name="技术部经理",
            im_user_id="u-xie",
            im_display_name="谢非",
            created_by="admin",
        )
        bindings = list_ratemin_bindings()

    assert result["unmatched"] == 1
    assert binding["im_user_id"] == "u-xie"
    assert any(item["rate_oper_id"] == "343" for item in bindings)


def test_ratemin_duplicate_ingest_does_not_resend(tmp_path) -> None:
    from src.platform.employee_bot_service import activate_employee_bot
    from src.platform.ratemin_service import ingest_ratemin_events
    from src.store.database import Database

    db_path = str(tmp_path / "ratemin-duplicate.db")
    sent: list[str] = []
    event = {
        "source_db": "business_a",
        "flow_id": "215",
        "flow_post_id": "63948",
        "data_id": "1176191",
        "task_id": "405",
        "recipient_oper_id": "309",
        "recipient_name": "员工甲_ZHANG Xiaolin",
        "subject": "DY26008",
        "content": "请尽快查阅",
    }
    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False), \
         patch("src.platform.employee_bot_service._derive_employee_access", return_value={
             "role": "self",
             "default_scope": "personal:u-zhang",
             "readable_scopes": ["personal:u-zhang"],
             "writable_scopes": ["personal:u-zhang"],
             "permissions": ["chat.use"],
         }), \
         patch("src.platform.ratemin_service.provider_outbound.send_platform_text", side_effect=lambda p, u, t: sent.append(t) or True):
        _reset_db(db_path)
        conn = Database.get(db_path).connect()
        conn.execute("INSERT INTO org_users(platform,user_id,name) VALUES('wecom','u-zhang','员工甲')")
        conn.commit()
        activate_employee_bot(platform="wecom", user_id="u-zhang", notify=False)
        first = ingest_ratemin_events([event])
        second = ingest_ratemin_events([event])

    assert first["notified"] == 1
    assert second["updated"] == 1
    assert len(sent) == 1


def test_ratemin_bound_user_waits_without_employee_bot_activation(tmp_path) -> None:
    from src.platform.ratemin_service import bind_ratemin_user, ingest_ratemin_events
    from src.store.database import Database

    db_path = str(tmp_path / "ratemin-bound-no-bot.db")
    sent: list[tuple[str, str, str]] = []
    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False), \
         patch("src.platform.ratemin_service.provider_outbound.send_platform_text", side_effect=lambda p, u, t: sent.append((p, u, t)) or True):
        _reset_db(db_path)
        Database.get(db_path).connect()
        bind_ratemin_user(
            source_db="business_a",
            rate_oper_id="309",
            rate_login_name="ZHANG_Xiaolin",
            rate_display_name="员工甲_ZHANG Xiaolin",
            im_user_id="u-zhang",
            im_display_name="员工甲",
        )
        result = ingest_ratemin_events(
            [
                {
                    "source_db": "business_a",
                    "flow_id": "215",
                    "flow_post_id": "63948",
                    "data_id": "1176191",
                    "task_id": "405",
                    "recipient_oper_id": "309",
                    "recipient_login_name": "ZHANG_Xiaolin",
                    "recipient_name": "员工甲_ZHANG Xiaolin",
                    "subject": "DY26008",
                    "content": "请尽快查阅",
                }
            ]
        )

    assert result["inserted"] == 1
    assert result["notified"] == 0
    assert result["skipped"] == 1
    assert sent == []


def test_ratemin_disabled_employee_bot_blocks_notification(tmp_path) -> None:
    from src.platform.employee_bot_service import activate_employee_bot, deactivate_employee_bot
    from src.platform.ratemin_service import bind_ratemin_user, ingest_ratemin_events
    from src.store.database import Database

    db_path = str(tmp_path / "ratemin-disabled-bot.db")
    sent: list[tuple[str, str, str]] = []
    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False), \
         patch("src.platform.employee_bot_service._notify_employee", return_value="sent"), \
         patch("src.platform.employee_bot_service._derive_employee_access", return_value={
             "role": "self",
             "default_scope": "personal:u-zhang",
             "readable_scopes": ["personal:u-zhang"],
             "writable_scopes": ["personal:u-zhang"],
             "permissions": ["chat.use"],
         }), \
         patch("src.platform.ratemin_service.provider_outbound.send_platform_text", side_effect=lambda p, u, t: sent.append((p, u, t)) or True):
        _reset_db(db_path)
        Database.get(db_path).connect()
        activate_employee_bot(platform="wecom", user_id="u-zhang", notify=False)
        deactivate_employee_bot(platform="wecom", user_id="u-zhang", updated_by="admin")
        bind_ratemin_user(
            source_db="business_a",
            rate_oper_id="309",
            rate_login_name="ZHANG_Xiaolin",
            rate_display_name="员工甲_ZHANG Xiaolin",
            im_user_id="u-zhang",
            im_display_name="员工甲",
        )
        result = ingest_ratemin_events(
            [
                {
                    "source_db": "business_a",
                    "flow_id": "215",
                    "flow_post_id": "63948",
                    "data_id": "1176191",
                    "task_id": "405",
                    "recipient_oper_id": "309",
                    "recipient_login_name": "ZHANG_Xiaolin",
                    "recipient_name": "员工甲_ZHANG Xiaolin",
                    "subject": "DY26008",
                    "content": "请尽快查阅",
                }
            ]
        )

    assert result["inserted"] == 1
    assert result["notified"] == 0
    assert result["skipped"] == 1
    assert sent == []


def test_ratemin_ingest_token_required(monkeypatch) -> None:
    from src.platform.ratemin_service import verify_ratemin_ingest_token

    monkeypatch.delenv("RATEMIN_INGEST_TOKEN", raising=False)
    assert verify_ratemin_ingest_token("x") is False
    monkeypatch.setenv("RATEMIN_INGEST_TOKEN", "secret")
    assert verify_ratemin_ingest_token("secret") is True


def test_ratemin_user_snapshot_ingest_and_auto_bind_all(tmp_path) -> None:
    from src.platform.ratemin_service import auto_bind_all_ratemin_users, ingest_ratemin_user_snapshots, list_ratemin_directory
    from src.store.database import Database

    db_path = str(tmp_path / "ratemin-users.db")
    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False):
        _reset_db(db_path)
        conn = Database.get(db_path).connect()
        conn.execute("INSERT INTO org_users(platform,user_id,name) VALUES('wecom','u-liu','员工乙')")
        conn.execute("INSERT INTO org_users(platform,user_id,name) VALUES('wecom','u-zhang','员工甲')")
        conn.commit()
        ingest = ingest_ratemin_user_snapshots(
            [
                {"source_db": "business_a", "rate_oper_id": "269", "rate_login_name": "LIU_Beibei", "rate_display_name": "员工乙_LIU Beibei"},
                {"source_db": "business_a", "rate_oper_id": "309", "rate_login_name": "ZHANG_Xiaolin", "rate_display_name": "员工甲_ZHANG Xiaolin"},
                {"source_db": "business_b", "rate_oper_id": "343", "rate_login_name": "343", "rate_display_name": "技术部经理"},
            ],
            auto_bind=False,
        )
        before = list_ratemin_directory()
        result = auto_bind_all_ratemin_users()
        after = list_ratemin_directory()

    assert ingest["snapshots"] == 3
    assert sum(1 for item in before if item["directory_status"] == "bound") == 0
    assert result["bound"] == 2
    assert result["unmatched"] == 1
    assert sum(1 for item in after if item["directory_status"] == "bound") == 2


def test_ratemin_directory_query_and_sort(tmp_path) -> None:
    from src.platform.ratemin_service import ingest_ratemin_user_snapshots, list_ratemin_directory
    from src.store.database import Database

    db_path = str(tmp_path / "ratemin-directory-sort.db")
    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False):
        _reset_db(db_path)
        Database.get(db_path).connect()
        ingest_ratemin_user_snapshots(
            [
                {"source_db": "business_a", "rate_oper_id": "100", "rate_login_name": "ZHANG_Xiaolin", "rate_display_name": "员工甲_ZHANG Xiaolin"},
                {"source_db": "business_a", "rate_oper_id": "200", "rate_login_name": "HAN_Bin", "rate_display_name": "李四_HAN Bin"},
                {"source_db": "business_b", "rate_oper_id": "300", "rate_login_name": "YU_Lin", "rate_display_name": "王五_YU Lin"},
            ],
            auto_bind=False,
        )
        filtered = list_ratemin_directory(query="李", sort="rate_oper_id", direction="desc")
        ent_only = list_ratemin_directory(source_db="business_b")
        by_oper_desc = list_ratemin_directory(sort="rate_oper_id", direction="desc")

    assert [item["rate_oper_id"] for item in filtered] == ["200"]
    assert [item["source_db"] for item in ent_only] == ["business_b"]
    assert [item["rate_oper_id"] for item in by_oper_desc] == ["300", "200", "100"]


def test_ratemin_source_databases_can_be_configured_by_environment() -> None:
    from src.platform.ratemin_service import configured_source_dbs

    with patch.dict("os.environ", {"RATEMIN_SOURCE_DBS": "workflow_a, workflow_b"}, clear=False):
        assert configured_source_dbs() == ("workflow_a", "workflow_b")


def test_admin_can_query_specific_user_ratemin_todos(tmp_path) -> None:
    from src.platform.employee_bot_service import activate_employee_bot
    from src.platform.ratemin_service import format_ratemin_todos_for_target, ingest_ratemin_events, sync_ratemin_current_events
    from src.store.database import Database

    db_path = str(tmp_path / "ratemin-admin-query.db")
    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False), \
         patch("src.platform.employee_bot_service._derive_employee_access", return_value={
             "role": "self",
             "default_scope": "personal:u-zhang",
             "readable_scopes": ["personal:u-zhang"],
             "writable_scopes": ["personal:u-zhang"],
             "permissions": ["chat.use"],
         }), \
         patch("src.platform.ratemin_service._is_platform_admin", return_value=True), \
         patch("src.platform.ratemin_service.provider_outbound.send_platform_text", return_value=True):
        _reset_db(db_path)
        conn = Database.get(db_path).connect()
        conn.execute("INSERT INTO org_users(platform,user_id,name) VALUES('wecom','u-admin','张三')")
        conn.execute("INSERT INTO org_users(platform,user_id,name) VALUES('wecom','u-zhang','员工甲')")
        conn.commit()
        activate_employee_bot(platform="wecom", user_id="u-zhang", notify=False)
        event = {
                    "source_db": "business_a",
                    "flow_id": "215",
                    "flow_post_id": "63948",
                    "data_id": "1176191",
                    "task_id": "405",
                    "recipient_oper_id": "309",
                    "recipient_login_name": "ZHANG_Xiaolin",
                    "recipient_name": "员工甲_ZHANG Xiaolin",
                    "subject": "DY26008",
                    "content": "请尽快查阅",
                    "todo_time": "2026-07-15 08:01:56",
                    "initiator_name": "钱七_WEI Yongsen",
                }
        ingest_ratemin_events([event])
        sync_ratemin_current_events([event], source_databases=["business_a"])
        message = format_ratemin_todos_for_target(platform="wecom", requester_user_id="u-admin", target_user="员工甲", query="DY26008")

    assert "员工甲 当前有 1 条业务系统待办" in message
    assert "DY26008" in message


def test_non_admin_cannot_query_other_user_ratemin_todos(tmp_path) -> None:
    from src.platform.ratemin_service import format_ratemin_todos_for_target
    from src.store.database import Database

    db_path = str(tmp_path / "ratemin-noadmin-query.db")
    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False), \
         patch("src.platform.ratemin_service._is_platform_admin", return_value=False):
        _reset_db(db_path)
        conn = Database.get(db_path).connect()
        conn.execute("INSERT INTO org_users(platform,user_id,name) VALUES('wecom','u-a','张三')")
        conn.execute("INSERT INTO org_users(platform,user_id,name) VALUES('wecom','u-b','员工甲')")
        conn.commit()
        message = format_ratemin_todos_for_target(platform="wecom", requester_user_id="u-a", target_user="员工甲", query="")

    assert "没有管理员权限" in message


def test_ratemin_failed_delivery_is_retried_by_pending_notifier(tmp_path) -> None:
    from src.platform.employee_bot_service import activate_employee_bot
    from src.platform.ratemin_service import flush_pending_ratemin_notifications, ingest_ratemin_events
    from src.store.database import Database

    db_path = str(tmp_path / "ratemin-retry-send-failed.db")
    attempts: list[str] = []
    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False), \
         patch("src.platform.employee_bot_service._derive_employee_access", return_value={
             "role": "self",
             "default_scope": "personal:u-zhang",
             "readable_scopes": ["personal:u-zhang"],
             "writable_scopes": ["personal:u-zhang"],
             "permissions": ["chat.use"],
         }), \
         patch("src.platform.ratemin_service.provider_outbound.send_platform_text", side_effect=lambda *_: attempts.append("send") or len(attempts) > 1):
        _reset_db(db_path)
        conn = Database.get(db_path).connect()
        conn.execute("INSERT INTO org_users(platform,user_id,name) VALUES('wecom','u-zhang','Zhang')")
        conn.commit()
        activate_employee_bot(platform="wecom", user_id="u-zhang", notify=False)
        first = ingest_ratemin_events([
            {
                "source_db": "business_a",
                "flow_id": "1",
                "flow_post_id": "2",
                "data_id": "3",
                "task_id": "4",
                "recipient_oper_id": "309",
                "recipient_name": "Zhang",
                "subject": "Retry me",
                "content": "Please handle",
            }
        ])
        retried = flush_pending_ratemin_notifications("wecom")

    assert first["inserted"] == 1
    assert first["notified"] == 0
    assert retried["sent"] == 1
    assert len(attempts) == 2


def test_ratemin_pending_notifier_recovers_no_active_when_user_is_now_active(tmp_path) -> None:
    from src.platform.employee_bot_service import _conn as employee_bot_conn
    from src.platform.ratemin_service import bind_ratemin_user, flush_pending_ratemin_notifications, ingest_ratemin_events
    from src.store.database import Database

    db_path = str(tmp_path / "ratemin-recover-no-active.db")
    sent: list[str] = []
    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False), \
         patch("src.platform.employee_bot_service._derive_employee_access", return_value={
             "role": "self",
             "default_scope": "personal:u-zhang",
             "readable_scopes": ["personal:u-zhang"],
             "writable_scopes": ["personal:u-zhang"],
             "permissions": ["chat.use"],
         }), \
         patch("src.platform.ratemin_service.provider_outbound.send_platform_text", side_effect=lambda *_: sent.append("send") or True):
        _reset_db(db_path)
        conn = Database.get(db_path).connect()
        conn.execute("INSERT INTO org_users(platform,user_id,name) VALUES('wecom','u-zhang','Zhang')")
        conn.commit()
        bind_ratemin_user(
            source_db="business_a",
            rate_oper_id="309",
            rate_display_name="Zhang",
            im_user_id="u-zhang",
            im_display_name="Zhang",
        )
        waiting = ingest_ratemin_events([
            {
                "source_db": "business_a",
                "flow_id": "1",
                "flow_post_id": "2",
                "data_id": "3",
                "task_id": "4",
                "recipient_oper_id": "309",
                "recipient_name": "Zhang",
                "subject": "Recover me",
                "content": "Please handle",
            }
        ])
        employee_bot_conn()
        now = 1.0
        conn.execute(
            """
            INSERT INTO employee_bot_assignments
                (platform, user_id, display_name, scope, permissions_json, status, activated_by, notify_status, created_at, updated_at)
            VALUES('wecom', 'u-zhang', '企业 AI 助手', 'personal', '[]', 'active', 'admin', 'not_requested', ?, ?)
            """,
            (now, now),
        )
        conn.commit()
        recovered = flush_pending_ratemin_notifications("wecom")

    assert waiting["skipped"] == 1
    assert recovered["sent"] == 1
    assert sent == ["send"]


def test_ratemin_user_query_filters_stale_todos_by_current_snapshot(tmp_path) -> None:
    from src.platform.employee_bot_service import activate_employee_bot
    from src.platform.ratemin_service import ingest_ratemin_events, query_my_ratemin_todos, sync_ratemin_current_events
    from src.store.database import Database

    db_path = str(tmp_path / "ratemin-current-query.db")
    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False), \
         patch("src.platform.employee_bot_service._derive_employee_access", return_value={
             "role": "self",
             "default_scope": "personal:u-zhang",
             "readable_scopes": ["personal:u-zhang"],
             "writable_scopes": ["personal:u-zhang"],
             "permissions": ["chat.use"],
         }), \
         patch("src.platform.ratemin_service.provider_outbound.send_platform_text", return_value=True):
        _reset_db(db_path)
        conn = Database.get(db_path).connect()
        conn.execute("INSERT INTO org_users(platform,user_id,name) VALUES('wecom','u-zhang','Zhang')")
        conn.commit()
        activate_employee_bot(platform="wecom", user_id="u-zhang", notify=False)
        stale = {
            "source_db": "business_a",
            "flow_id": "1",
            "flow_post_id": "2",
            "data_id": "old",
            "task_id": "4",
            "recipient_oper_id": "309",
            "recipient_name": "Zhang",
            "subject": "Old todo",
        }
        active = {
            "source_db": "business_a",
            "flow_id": "1",
            "flow_post_id": "2",
            "data_id": "new",
            "task_id": "4",
            "recipient_oper_id": "309",
            "recipient_name": "Zhang",
            "subject": "Current todo",
        }
        ingest_ratemin_events([stale, active])
        sync_ratemin_current_events([active], source_databases=["business_a"])
        todos = query_my_ratemin_todos(platform="wecom", user_id="u-zhang")

    assert todos["count"] == 1
    assert "Current todo" in todos["message"]
    assert "Old todo" not in todos["message"]
