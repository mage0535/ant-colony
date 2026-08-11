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
    sent_messages: list[tuple[str, str, str]] = []

    def fake_send_text(platform: str, user_id: str, content: str) -> bool:
        sent_messages.append((platform, user_id, content))
        return True

    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False), \
         patch("src.gateway.provider_outbound.send_platform_text", side_effect=fake_send_text), \
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
    assert sent_messages[-1][0] == "wecom"
    assert sent_messages[-1][1] == "u-employee"
    message = sent_messages[-1][2]
    assert "你的企业 AI 助手已开通：企业 AI 助手" in message
    assert len(message.encode("utf-8")) > 2048
    assert "我能帮你做什么" in message
    for feature in [
        "知识库问答",
        "文档处理",
        "企业应用查询",
        "审批与流程提醒",
        "业务系统通知与查询",
        "邮箱未读统计",
        "待办和任务协作",
        "会议和日程协助",
        "联网检索",
        "公共信息订阅",
        "专家角色协助",
    ]:
        assert feature in message
    assert "你的名字叫小智" in message
    assert "如果某项能力提示未配置" in message
    assert "处于测试和持续优化阶段" in message
    assert "联系公司 IT 人员反馈" in message


def test_send_employee_bot_welcome_uses_unified_outbound_for_all_platforms(tmp_path) -> None:
    from src.platform.employee_bot_service import send_employee_bot_welcome
    from src.store.database import Database

    db_path = str(tmp_path / "employee-bot-unified-outbound.db")
    sent: list[tuple[str, str, str]] = []

    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False), \
         patch("src.gateway.provider_outbound.send_platform_text", side_effect=lambda p, u, t: sent.append((p, u, t)) or True):
        Database.get(db_path).close()
        Database._instances.pop(db_path, None)  # type: ignore[attr-defined]

        feishu = send_employee_bot_welcome(platform="feishu", user_id="open-id-1", display_name="飞书 AI 助手")
        dingtalk = send_employee_bot_welcome(platform="dingtalk", user_id="ding-user-1", display_name="钉钉 AI 助手")

    assert feishu["notify_status"] == "sent"
    assert dingtalk["notify_status"] == "sent"
    assert [item[0] for item in sent] == ["feishu", "dingtalk"]
    assert sent[0][1] == "open-id-1"
    assert sent[1][1] == "ding-user-1"


def test_employee_bot_accepts_wecom_bot_platform_alias(tmp_path) -> None:
    from src.platform.employee_bot_service import activate_employee_bot
    from src.store.database import Database

    db_path = str(tmp_path / "employee-bot-platform-alias.db")
    sent: list[tuple[str, str, str]] = []

    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path}, clear=False), \
         patch("src.gateway.provider_outbound.send_platform_text", side_effect=lambda p, u, t: sent.append((p, u, t)) or True):
        Database.get(db_path).close()
        Database._instances.pop(db_path, None)  # type: ignore[attr-defined]

        result = activate_employee_bot(platform="wecom_bot", user_id="u-alias", display_name="企业 AI 助手")

    assert result["platform"] == "wecom"
    assert result["notify_status"] == "sent"
    assert sent[0][0] == "wecom"


def test_employee_bot_welcome_message_has_complete_function_list() -> None:
    from src.platform.employee_bot_service import build_employee_bot_welcome_message

    message = build_employee_bot_welcome_message("示例企业AI助手")

    assert "示例企业AI助手" in message
    assert len(message.encode("utf-8")) > 2048
    assert message.count("\n") >= 15
    assert "组织架构权限返回答案" in message
    assert "直接推送文件" in message
    assert "业务系统有新待办" in message
    assert "AI 助手只提醒和查询，不代替你审批" in message
    assert "不会读取正文摘要、代发邮件或回复邮件" in message
    assert "你的名字叫小智" in message
    assert "发现任何问题" in message
    assert "需要增加的功能" in message


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
            ("?????????? AI ??????????", "wecom", "u-employee"),
        )
        conn.commit()

        assignments = list_employee_bot_assignments("wecom")
        stored_name = conn.execute(
            "SELECT display_name FROM employee_bot_assignments WHERE platform = ? AND user_id = ?",
            ("wecom", "u-employee"),
        ).fetchone()[0]

    assert assignments[0]["display_name"] == "企业 AI 助手"
    assert stored_name == "企业 AI 助手"


def test_activate_employee_bot_recovers_existing_ratemin_binding_and_pending_delivery(tmp_path) -> None:
    from src.platform.employee_bot_service import activate_employee_bot
    from src.platform.ratemin_service import bind_ratemin_user, ingest_ratemin_events
    from src.store.database import Database

    db_path = str(tmp_path / "employee-bot-ratemin-recover.db")
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
        Database.get(db_path).close()
        Database._instances.pop(db_path, None)  # type: ignore[attr-defined]
        conn = Database.get(db_path).connect()
        conn.execute("INSERT INTO org_users(platform,user_id,name) VALUES('wecom','u-zhang','员工甲')")
        conn.commit()
        bind_ratemin_user(
            source_db="business_a",
            rate_oper_id="309",
            rate_login_name="ZHANG_Xiaolin",
            rate_display_name="员工甲_ZHANG Xiaolin",
            im_user_id="u-zhang",
            im_display_name="员工甲",
        )
        ingest_result = ingest_ratemin_events(
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
                    "todo_time": "2026-07-15 08:01:56",
                }
            ]
        )
        assert ingest_result["inserted"] == 1
        row_before = conn.execute(
            "SELECT delivery_status FROM ratemin_pending_events WHERE source_db = ? AND recipient_oper_id = ?",
            ("business_a", "309"),
        ).fetchone()
        activate_employee_bot(platform="wecom", user_id="u-zhang", notify=False)
        row_after = conn.execute(
            "SELECT delivery_status FROM ratemin_pending_events WHERE source_db = ? AND recipient_oper_id = ?",
            ("business_a", "309"),
        ).fetchone()

    assert row_before["delivery_status"] == "no_active_ai_assistant"
    assert row_after["delivery_status"] == "sent"
    assert sent and sent[0][1] == "u-zhang"
