from __future__ import annotations

from unittest.mock import patch


def _reset_db(db_path: str) -> None:
    from src.store.database import Database

    Database.get(db_path).close()
    Database._instances.pop(db_path, None)  # type: ignore[attr-defined]


def test_process_change_notifier_only_notifies_applicant_on_status_change(tmp_path) -> None:
    from src.platform.employee_bot_service import activate_employee_bot
    from src.platform.process_change_notifier import _conn, run_process_change_notifier
    from src.store.database import Database

    db_path = str(tmp_path / "process-notifier.db")
    sent: list[tuple[str, str, str]] = []

    first = "报销审批（SP1）：审批中，申请人 u-applicant，当前节点 主管审批"
    second = "报销审批（SP1）：已通过，申请人 u-applicant，当前节点 完成"

    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False), \
         patch("src.platform.employee_bot_service._derive_employee_access", return_value={
             "role": "self",
             "default_scope": "personal:u-applicant",
             "readable_scopes": ["personal:u-applicant"],
             "writable_scopes": ["personal:u-applicant"],
             "permissions": ["chat.use", "approval.read"],
         }), \
         patch("src.platform.process_change_notifier.provider_outbound.send_platform_text", side_effect=lambda p, u, t: sent.append((p, u, t)) or True):
        _reset_db(db_path)
        activate_employee_bot(platform="wecom", user_id="u-applicant", notify=False)

        def fake_first(capability_id, *args, context=None, empty_message=""):
            assert capability_id == "approval.list"
            assert args == ("all",)
            assert context.user_id == "u-applicant"
            return first

        def fake_second(capability_id, *args, context=None, empty_message=""):
            assert capability_id == "approval.list"
            assert args == ("all",)
            assert context.user_id == "u-applicant"
            return second

        with patch("src.platform.process_change_notifier.invoke_capability", side_effect=fake_first):
            first_result = run_process_change_notifier("wecom")
        with patch("src.platform.process_change_notifier.invoke_capability", side_effect=fake_second):
            second_result = run_process_change_notifier("wecom")

        row = Database.get(db_path).connect().execute(
            "SELECT status, current_node FROM process_status_snapshots WHERE applicant_user_id = ?",
            ("u-applicant",),
        ).fetchone()

    assert first_result["checked"] == 1
    assert first_result["notified"] == 0
    assert second_result["changed"] == 1
    assert second_result["notified"] == 1
    assert sent == [("wecom", "u-applicant", sent[0][2])]
    assert "流程状态变更" in sent[0][2]
    assert "审批中 -> 已通过" in sent[0][2]
    assert row["status"] == "已通过"
    assert row["current_node"] == "完成"


def test_process_change_notifier_ignores_users_without_active_ai_assistant(tmp_path) -> None:
    from src.platform.process_change_notifier import run_process_change_notifier

    db_path = str(tmp_path / "process-notifier-empty.db")
    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False), \
         patch("src.platform.process_change_notifier.invoke_capability") as invoke:
        _reset_db(db_path)
        result = run_process_change_notifier("wecom")

    assert result["users"] == 0
    assert result["checked"] == 0
    invoke.assert_not_called()


def test_process_change_notifier_reports_structured_wecom_credential_error(tmp_path) -> None:
    from src.platform.employee_bot_service import activate_employee_bot
    from src.platform.process_change_notifier import run_process_change_notifier

    db_path = str(tmp_path / "process-notifier-credential-error.db")
    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False), \
         patch("src.platform.employee_bot_service._derive_employee_access", return_value={
             "role": "self", "default_scope": "personal:u1", "readable_scopes": [], "writable_scopes": [], "permissions": [],
         }), \
         patch("src.platform.process_change_notifier._load_structured_process_items", return_value=([], "WeCom token error: corpsecret missing, hint: [123], more info at https://example.test")), \
         patch("src.platform.process_change_notifier.invoke_capability", return_value=""):
        _reset_db(db_path)
        activate_employee_bot(platform="wecom", user_id="u1", notify=False)
        result = run_process_change_notifier("wecom")

    assert result["checked"] == 0
    assert result["notified"] == 0
    assert result["errors"]
    assert "企微审批/流程凭据缺失" in result["errors"][0]
    assert "hint" not in result["errors"][0]
    assert "http" not in result["errors"][0]


def test_process_change_notifier_retries_a_change_after_delivery_failure(tmp_path) -> None:
    from src.platform.employee_bot_service import activate_employee_bot
    from src.platform.process_change_notifier import run_process_change_notifier

    db_path = str(tmp_path / "process-notifier-retry.db")
    first = "采购审批（SP2）：审批中，申请人 u1，当前节点 部门负责人"
    second = "采购审批（SP2）：已通过，申请人 u1，当前节点 完成"
    attempts: list[str] = []
    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False), \
         patch("src.platform.employee_bot_service._derive_employee_access", return_value={
             "role": "self", "default_scope": "personal:u1", "readable_scopes": [], "writable_scopes": [], "permissions": [],
         }), \
         patch("src.platform.process_change_notifier.invoke_capability", side_effect=[first, second, second]), \
         patch("src.platform.process_change_notifier.provider_outbound.send_platform_text", side_effect=lambda *_: attempts.append("send") or len(attempts) > 1):
        _reset_db(db_path)
        activate_employee_bot(platform="wecom", user_id="u1", notify=False)
        run_process_change_notifier("wecom")
        failed = run_process_change_notifier("wecom")
        retried = run_process_change_notifier("wecom")

    assert failed["notified"] == 0
    assert retried["notified"] == 1
    assert attempts == ["send", "send"]


def test_process_change_notifier_retries_first_handler_assignment_after_delivery_failure(tmp_path) -> None:
    from src.platform.employee_bot_service import activate_employee_bot
    from src.platform.process_change_notifier import run_process_change_notifier

    db_path = str(tmp_path / "process-handler-retry.db")
    item = {
        "source": "approval",
        "item_id": "SP-FIRST-HANDLER",
        "title": "请假申请",
        "status": "审批中",
        "current_node": "部门负责人审批",
        "applicant_user_id": "u-applicant",
        "applicant_name": "张三",
        "recipient_user_ids": ["u-manager"],
        "content": "请假 1 天",
        "event_time": "2026-07-17 09:00",
    }
    attempts: list[str] = []

    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False), \
         patch("src.platform.employee_bot_service._derive_employee_access", return_value={
             "role": "self", "default_scope": "personal", "readable_scopes": [], "writable_scopes": [], "permissions": [],
         }), \
         patch("src.platform.process_change_notifier._load_user_process_items", return_value=([item], "")), \
         patch("src.platform.process_change_notifier.provider_outbound.send_platform_text", side_effect=lambda *_: attempts.append("send") or len(attempts) > 1):
        _reset_db(db_path)
        activate_employee_bot(platform="wecom", user_id="u-manager", notify=False)
        failed = run_process_change_notifier("wecom")
        retried = run_process_change_notifier("wecom")

    assert failed["notified"] == 0
    assert failed["errors"]
    assert retried["notified"] == 1
    assert attempts == ["send", "send"]


def test_process_change_notifier_dry_run_does_not_send_or_write_snapshot(tmp_path) -> None:
    from src.platform.employee_bot_service import activate_employee_bot
    from src.platform.process_change_notifier import run_process_change_notifier
    from src.store.database import Database

    db_path = str(tmp_path / "process-dry-run.db")
    item = {
        "source": "approval",
        "item_id": "SP-DRY-RUN",
        "title": "请假申请",
        "status": "审批中",
        "current_node": "部门负责人审批",
        "applicant_user_id": "u-applicant",
        "applicant_name": "张三",
        "recipient_user_ids": ["u-manager"],
        "content": "请假 1 天",
        "event_time": "2026-07-17 09:00",
    }

    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False), \
         patch("src.platform.employee_bot_service._derive_employee_access", return_value={
             "role": "self", "default_scope": "personal", "readable_scopes": [], "writable_scopes": [], "permissions": [],
         }), \
         patch("src.platform.process_change_notifier._load_user_process_items", return_value=([item], "")), \
         patch("src.platform.process_change_notifier.provider_outbound.send_platform_text") as send:
        _reset_db(db_path)
        activate_employee_bot(platform="wecom", user_id="u-manager", notify=False)
        result = run_process_change_notifier("wecom", dry_run=True)
        row_count = Database.get(db_path).connect().execute("SELECT COUNT(*) AS n FROM process_status_snapshots").fetchone()["n"]
        audit_count = Database.get(db_path).connect().execute("SELECT COUNT(*) AS n FROM process_notification_audit").fetchone()["n"]

    assert result["dry_run"] is True
    assert result["notified"] == 1
    assert row_count == 0
    assert audit_count == 0
    send.assert_not_called()


def test_process_change_notifier_notifies_current_handler_on_first_assignment(tmp_path) -> None:
    from src.platform.employee_bot_service import activate_employee_bot
    from src.platform.process_change_notifier import run_process_change_notifier

    db_path = str(tmp_path / "process-handler.db")
    sent: list[tuple[str, str, str]] = []
    item = {
        "source": "approval",
        "item_id": "SP-LEAVE-1",
        "title": "请假申请",
        "status": "审批中",
        "current_node": "部门负责人审批",
        "applicant_user_id": "u-applicant",
        "applicant_name": "张三",
        "recipient_user_ids": ["u-manager"],
        "content": "请假 1 天",
        "event_time": "2026-07-17 09:00",
    }

    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False), \
         patch("src.platform.employee_bot_service._derive_employee_access", return_value={
             "role": "self", "default_scope": "personal", "readable_scopes": [], "writable_scopes": [], "permissions": [],
         }), \
         patch("src.platform.process_change_notifier._load_user_process_items", return_value=([item], "")), \
         patch("src.platform.process_change_notifier.provider_outbound.send_platform_text", side_effect=lambda p, u, t: sent.append((p, u, t)) or True):
        _reset_db(db_path)
        activate_employee_bot(platform="wecom", user_id="u-applicant", notify=False)
        activate_employee_bot(platform="wecom", user_id="u-manager", notify=False)
        result = run_process_change_notifier("wecom")

    assert result["checked"] == 2
    assert result["notified"] == 1
    assert sent == [("wecom", "u-manager", sent[0][2])]
    assert "【流程待办提醒】" in sent[0][2]
    assert "发起人：张三" in sent[0][2]
    assert "日期时间：2026-07-17 09:00" in sent[0][2]
    assert "内容：请假 1 天" in sent[0][2]


def test_process_change_notifier_notifies_applicant_on_node_change(tmp_path) -> None:
    from src.platform.employee_bot_service import activate_employee_bot
    from src.platform.process_change_notifier import run_process_change_notifier

    db_path = str(tmp_path / "process-applicant-node.db")
    sent: list[tuple[str, str, str]] = []
    first = {
        "source": "approval",
        "item_id": "SP-LEAVE-2",
        "title": "请假申请",
        "status": "审批中",
        "current_node": "部门负责人审批",
        "applicant_user_id": "u-applicant",
        "applicant_name": "张三",
        "recipient_user_ids": ["u-manager"],
        "content": "请假 2 天",
        "event_time": "2026-07-17 09:00",
    }
    second = {**first, "current_node": "人事审批", "recipient_user_ids": ["u-hr"], "event_time": "2026-07-17 10:00"}

    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False), \
         patch("src.platform.employee_bot_service._derive_employee_access", return_value={
             "role": "self", "default_scope": "personal", "readable_scopes": [], "writable_scopes": [], "permissions": [],
         }), \
         patch("src.platform.process_change_notifier.provider_outbound.send_platform_text", side_effect=lambda p, u, t: sent.append((p, u, t)) or True):
        _reset_db(db_path)
        activate_employee_bot(platform="wecom", user_id="u-applicant", notify=False)
        with patch("src.platform.process_change_notifier._load_user_process_items", return_value=([first], "")):
            run_process_change_notifier("wecom")
        with patch("src.platform.process_change_notifier._load_user_process_items", return_value=([second], "")):
            result = run_process_change_notifier("wecom")

    applicant_messages = [msg for _, user, msg in sent if user == "u-applicant"]
    assert result["notified"] >= 1
    assert applicant_messages
    assert "【流程状态变更】" in applicant_messages[-1]
    assert "发起人：张三" in applicant_messages[-1]
    assert "当前节点：部门负责人审批 -> 人事审批" in applicant_messages[-1]


def test_process_change_notifier_repairs_numeric_node_snapshot_without_notification(tmp_path) -> None:
    from src.platform.employee_bot_service import activate_employee_bot
    from src.platform.process_change_notifier import _conn, run_process_change_notifier
    from src.store.database import Database

    db_path = str(tmp_path / "process-parser-repair.db")
    item = {
        "source": "approval",
        "item_id": "SP-NODE-REPAIR",
        "title": "出差申请",
        "status": "审批中",
        "current_node": "当前审批人",
        "applicant_user_id": "u-applicant",
        "applicant_name": "张三",
        "recipient_user_ids": ["u-manager"],
        "content": "出差事由：客户拜访",
        "event_time": "2026-07-20 09:00",
    }

    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False), \
         patch("src.platform.employee_bot_service._derive_employee_access", return_value={
             "role": "self", "default_scope": "personal", "readable_scopes": [], "writable_scopes": [], "permissions": [],
         }), \
         patch("src.platform.process_change_notifier._load_user_process_items", return_value=([item], "")), \
         patch("src.platform.process_change_notifier.provider_outbound.send_platform_text") as send:
        _reset_db(db_path)
        activate_employee_bot(platform="wecom", user_id="u-applicant", notify=False)
        _conn()
        conn = Database.get(db_path).connect()
        conn.execute(
            """
            INSERT INTO process_status_snapshots
                (platform, applicant_user_id, source, item_id, title, status, current_node, fingerprint, snapshot_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "wecom",
                "u-applicant",
                "approval",
                "approval:SP-NODE-REPAIR:applicant",
                "出差申请",
                "审批中",
                "1",
                "old-parser-fingerprint",
                "{}",
                1,
                1,
            ),
        )
        conn.commit()
        result = run_process_change_notifier("wecom")
        row = conn.execute(
            "SELECT current_node FROM process_status_snapshots WHERE applicant_user_id = ? AND item_id = ?",
            ("u-applicant", "approval:SP-NODE-REPAIR:applicant"),
        ).fetchone()

    assert result["notified"] == 0
    assert row["current_node"] == "当前审批人"
    send.assert_not_called()
