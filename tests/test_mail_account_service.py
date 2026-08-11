from __future__ import annotations

import email
import os
from unittest.mock import MagicMock, patch


def test_mail_account_crud_masks_password(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "ant.db"))

    from src.platform.mail_account_service import (
        delete_mail_account,
        list_mail_accounts,
        save_mail_account,
        set_mail_account_status,
    )

    saved = save_mail_account(
        {
            "platform": "wecom",
            "user_id": "u1",
            "email_address": "u1@example.com",
            "imap_host": "imap.example.com",
            "imap_port": 993,
            "protocol": "imap",
            "username": "u1@example.com",
            "password": "secret",
            "poll_interval_minutes": 10,
            "enabled": True,
        },
        updated_by="admin",
    )

    assert saved["user_id"] == "u1"
    assert saved["password_configured"] is True
    assert "secret" not in str(saved)

    listed = list_mail_accounts(platform="wecom")["accounts"]
    assert listed[0]["email_address"] == "u1@example.com"
    assert listed[0]["account_label"] == "默认邮箱"
    assert listed[0]["poll_interval_minutes"] == 10
    assert listed[0]["protocol"] == "imap"
    assert "password" not in listed[0]

    disabled = set_mail_account_status("wecom", "u1", enabled=False, updated_by="admin")
    assert disabled["enabled"] is False

    deleted = delete_mail_account("wecom", "u1")
    assert deleted["deleted"] is True
    assert list_mail_accounts(platform="wecom")["accounts"] == []


def test_mail_account_list_joins_user_names_without_per_row_lookup(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "mail-list-fast.db"))

    from src.platform.mail_account_service import list_mail_accounts, save_mail_account
    from src.store.database import Database

    conn = Database.get().connect()
    conn.execute(
        "INSERT INTO org_users(platform,user_id,name,email) VALUES(?,?,?,?)",
        ("wecom", "u1", "张三", "u1@example.com"),
    )
    conn.commit()
    save_mail_account(
        {
            "platform": "wecom",
            "user_id": "u1",
            "email_address": "u1@example.com",
            "imap_host": "pop.example.com",
            "imap_port": 110,
            "protocol": "pop3",
            "encryption": "none",
            "username": "u1@example.com",
            "password": "secret",
        },
        updated_by="admin",
    )

    with patch("src.platform.mail_account_service._user_display_name", side_effect=AssertionError("N+1 lookup")):
        listed = list_mail_accounts(platform="wecom")["accounts"]

    assert listed[0]["user_name"] == "张三"


def test_mail_account_list_survives_shared_connection_dict_row_factory(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "mail-row-factory.db"))

    from src.knowledge.cloud_drive import _dict_factory
    from src.platform.mail_account_service import list_mail_accounts, save_mail_account
    from src.store.database import Database

    save_mail_account(
        {
            "platform": "wecom",
            "user_id": "u1",
            "email_address": "u1@example.com",
            "imap_host": "pop.example.com",
            "imap_port": 110,
            "protocol": "pop3",
            "encryption": "none",
            "username": "u1@example.com",
            "password": "secret",
        },
        updated_by="admin",
    )

    conn = Database.get().connect()
    conn.row_factory = _dict_factory

    listed = list_mail_accounts(platform="wecom")["accounts"]

    assert listed[0]["email_address"] == "u1@example.com"


def test_mail_account_supports_multiple_accounts_per_user(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "ant.db"))

    from src.platform.mail_account_service import list_mail_accounts, save_mail_account

    first = save_mail_account(
        {
            "platform": "wecom",
            "user_id": "u1",
            "account_label": "公司邮箱",
            "email_address": "u1@example.com",
            "imap_host": "imap.example.com",
            "imap_port": 993,
            "protocol": "imap",
            "username": "u1@example.com",
            "password": "secret1",
            "enabled": True,
        },
        updated_by="admin",
    )
    second = save_mail_account(
        {
            "platform": "wecom",
            "user_id": "u1",
            "account_label": "业务邮箱",
            "email_address": "u1-business@example.com",
            "imap_host": "imap2.example.com",
            "imap_port": 995,
            "protocol": "pop3",
            "username": "u1-business@example.com",
            "password": "secret2",
            "enabled": True,
        },
        updated_by="admin",
    )

    assert first["account_id"] != second["account_id"]
    accounts = list_mail_accounts(platform="wecom", user_id="u1")["accounts"]

    assert [account["email_address"] for account in accounts] == ["u1@example.com", "u1-business@example.com"]
    assert [account["account_label"] for account in accounts] == ["公司邮箱", "业务邮箱"]
    assert "secret1" not in str(accounts)
    assert "secret2" not in str(accounts)


def test_mail_account_changed_email_with_existing_account_id_creates_new_account(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "ant.db"))

    from src.platform.mail_account_service import get_mail_account_by_id, list_mail_accounts, save_mail_account

    first = save_mail_account(
        {
            "platform": "wecom",
            "user_id": "u1",
            "account_label": "公司邮箱",
            "email_address": "u1@example.com",
            "imap_host": "imap.example.com",
            "imap_port": 993,
            "protocol": "imap",
            "username": "u1@example.com",
            "password": "secret1",
            "enabled": True,
        },
        updated_by="admin",
    )

    second = save_mail_account(
        {
            "platform": "wecom",
            "user_id": "u1",
            "account_id": first["account_id"],
            "account_label": "业务邮箱",
            "email_address": "u1-business@example.com",
            "imap_host": "imap2.example.com",
            "imap_port": 995,
            "protocol": "pop3",
            "username": "u1-business@example.com",
            "password": "secret2",
            "enabled": True,
        },
        updated_by="admin",
    )

    assert second["account_id"] != first["account_id"]
    assert get_mail_account_by_id(first["account_id"])["email_address"] == "u1@example.com"
    accounts = list_mail_accounts(platform="wecom", user_id="u1")["accounts"]
    assert [account["email_address"] for account in accounts] == ["u1@example.com", "u1-business@example.com"]


def test_mail_account_save_infers_new_user_config_from_org_email_and_same_domain_template(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "ant.db"))

    from src.platform.mail_account_service import list_mail_accounts, save_mail_account
    from src.store.database import Database

    conn = Database.get().connect()
    conn.execute(
        "INSERT INTO org_users(platform,user_id,name,email) VALUES(?,?,?,?)",
        ("wecom", "u2", "张三", "zhang.san@example.com"),
    )
    conn.commit()
    save_mail_account(
        {
            "platform": "wecom",
            "user_id": "u-template",
            "email_address": "template@example.com",
            "account_label": "模板邮箱",
            "protocol": "pop3",
            "imap_host": "pop.example.com",
            "imap_port": 110,
            "encryption": "none",
            "username": "template@example.com",
            "password": "template-secret",
            "poll_interval_minutes": 5,
            "enabled": True,
        },
        updated_by="admin",
    )

    saved = save_mail_account(
        {
            "platform": "wecom",
            "user_id": "u2",
            "password": "secret",
            "enabled": True,
        },
        updated_by="admin",
    )

    assert saved["email_address"] == "zhang.san@example.com"
    assert saved["protocol"] == "pop3"
    assert saved["imap_host"] == "pop.example.com"
    assert saved["imap_port"] == 110
    assert saved["encryption"] == "none"
    assert saved["username"] == "zhang.san@example.com"
    assert saved["poll_interval_minutes"] == 1
    accounts = list_mail_accounts(platform="wecom", user_id="u2")["accounts"]
    assert len(accounts) == 1


def test_summarize_user_mailbox_reads_all_enabled_accounts_with_source_label(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "ant.db"))
    monkeypatch.setenv("ANT_COLONY_MAIL_LLM_SUMMARY", "0")

    from src.platform.mail_account_service import save_mail_account, summarize_user_mailbox

    save_mail_account(
        {
            "platform": "wecom",
            "user_id": "u1",
            "account_label": "公司邮箱",
            "email_address": "u1@example.com",
            "imap_host": "imap.example.com",
            "imap_port": 993,
            "protocol": "imap",
            "username": "u1@example.com",
            "password": "secret1",
            "enabled": True,
        },
        updated_by="admin",
    )
    save_mail_account(
        {
            "platform": "wecom",
            "user_id": "u1",
            "account_label": "业务邮箱",
            "email_address": "u1-business@example.com",
            "imap_host": "imap2.example.com",
            "imap_port": 993,
            "protocol": "imap",
            "username": "u1-business@example.com",
            "password": "secret2",
            "enabled": True,
        },
        updated_by="admin",
    )

    def raw_message(sender: str, subject: str, body: str) -> bytes:
        msg = email.message.EmailMessage()
        msg["From"] = sender
        msg["Subject"] = subject
        msg["Date"] = "Fri, 17 Jul 2026 08:30:00 +0800"
        msg.set_content(body)
        return msg.as_bytes()

    fake_first = MagicMock()
    fake_first.search.return_value = ("OK", [b"101"])
    fake_first.uid.return_value = ("OK", [(b"101 (RFC822 {123}", raw_message("a@example.com", "公司通知", "请确认公司邮箱邮件。"))])
    fake_second = MagicMock()
    fake_second.search.return_value = ("OK", [b"201"])
    fake_second.uid.return_value = ("OK", [(b"201 (RFC822 {123}", raw_message("b@example.com", "业务通知", "请确认业务邮箱邮件。"))])

    with patch("imaplib.IMAP4_SSL", side_effect=[fake_first, fake_second]):
        result = summarize_user_mailbox("wecom", "u1", limit=3)

    assert "来源邮箱：公司邮箱 <u1@example.com>" in result
    assert "来源邮箱：业务邮箱 <u1-business@example.com>" in result
    assert "当前有 1 封未读邮件" in result
    assert "邮件摘要功能已关闭" in result
    assert "标题：" not in result
    assert "公司通知" not in result
    assert fake_first.login.call_args.args == ("u1@example.com", "secret1")
    assert fake_second.login.call_args.args == ("u1-business@example.com", "secret2")
    fake_first.uid.assert_not_called()
    fake_second.uid.assert_not_called()


def test_summarize_single_mail_account_only_reads_requested_account(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "ant.db"))
    monkeypatch.setenv("ANT_COLONY_MAIL_LLM_SUMMARY", "0")

    from src.platform.mail_account_service import save_mail_account, summarize_mail_account

    first = save_mail_account(
        {
            "platform": "wecom",
            "user_id": "u1",
            "account_label": "公司邮箱",
            "email_address": "u1@example.com",
            "imap_host": "imap.example.com",
            "imap_port": 993,
            "protocol": "imap",
            "username": "u1@example.com",
            "password": "secret1",
            "enabled": True,
        }
    )
    save_mail_account(
        {
            "platform": "wecom",
            "user_id": "u1",
            "account_label": "招聘",
            "email_address": "hr@example.com",
            "imap_host": "imap2.example.com",
            "imap_port": 993,
            "protocol": "imap",
            "username": "hr@example.com",
            "password": "bad-secret",
            "enabled": True,
        }
    )

    msg = email.message.EmailMessage()
    msg["From"] = "a@example.com"
    msg["Subject"] = "公司通知"
    msg["Date"] = "Fri, 17 Jul 2026 08:30:00 +0800"
    msg.set_content("只测试公司邮箱。")
    fake_first = MagicMock()
    fake_first.search.return_value = ("OK", [b"101"])
    fake_first.uid.return_value = ("OK", [(b"101 (RFC822 {123}", msg.as_bytes())])

    with patch("imaplib.IMAP4_SSL", return_value=fake_first) as imap_cls:
        result = summarize_mail_account(first["account_id"], limit=3)

    assert "来源邮箱：公司邮箱 <u1@example.com>" in result
    assert "当前有 1 封未读邮件" in result
    assert "邮件摘要功能已关闭" in result
    assert "标题：" not in result
    assert "公司通知" not in result
    assert "招聘" not in result
    assert "hr@example.com" not in result
    imap_cls.assert_called_once_with("imap.example.com", 993)
    fake_first.login.assert_called_once_with("u1@example.com", "secret1")
    fake_first.uid.assert_not_called()


def test_mail_new_message_notifier_baselines_existing_messages(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "ant.db"))
    monkeypatch.setenv("ANT_COLONY_MAIL_FIRST_RUN_NOTIFY_SECONDS", "600")

    from src.platform import mail_account_service
    from src.platform.mail_account_service import save_mail_account, run_mail_new_message_notifier

    save_mail_account(
        {
            "platform": "wecom",
            "user_id": "u1",
            "email_address": "u1@example.com",
            "imap_host": "imap.example.com",
            "imap_port": 993,
            "protocol": "imap",
            "username": "u1@example.com",
            "password": "secret",
            "enabled": True,
        },
        updated_by="admin",
    )
    monkeypatch.setattr(mail_account_service.time, "time", lambda: 2000.0)
    items = [
        {
            "message_key": "old-1",
            "received_at": "old",
            "received_at_ts": 1000.0,
            "sender": "a@example.com",
            "subject": "历史邮件",
            "summary": "历史邮件摘要",
            "attachments": [],
            "text": "标题：历史邮件",
        }
    ]

    with patch("src.platform.mail_account_service._fetch_recent_mail_items", return_value=items), \
         patch("src.platform.mail_account_service._send_mail_notification") as send:
        result = run_mail_new_message_notifier(force=True)

    assert result["baselined"] == 1
    assert result["sent"] == 0
    send.assert_not_called()


def test_mail_new_message_notifier_pushes_only_new_messages_after_baseline(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "ant.db"))
    monkeypatch.setenv("ANT_COLONY_MAIL_FIRST_RUN_NOTIFY_SECONDS", "0")

    from src.platform import mail_account_service
    from src.platform.mail_account_service import save_mail_account, run_mail_new_message_notifier
    from src.store.database import Database

    save_mail_account(
        {
            "platform": "wecom",
            "user_id": "u1",
            "email_address": "u1@example.com",
            "imap_host": "imap.example.com",
            "imap_port": 993,
            "protocol": "imap",
            "username": "u1@example.com",
            "password": "secret",
            "poll_interval_minutes": 1,
            "enabled": True,
        },
        updated_by="admin",
    )
    conn = Database.get().connect()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS employee_bot_assignments (
            platform TEXT NOT NULL,
            user_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            UNIQUE(platform, user_id)
        )
        """
    )
    conn.execute(
        "INSERT OR REPLACE INTO employee_bot_assignments (platform,user_id,status) VALUES ('wecom','u1','active')"
    )
    conn.commit()

    old_item = {
        "message_key": "old-1",
        "received_at": "old",
        "received_at_ts": 1000.0,
        "sender": "a@example.com",
        "subject": "历史邮件",
        "summary": "历史邮件摘要",
        "attachments": [],
        "text": "标题：历史邮件",
    }
    new_item = {
        "message_key": "new-1",
        "received_at": "new",
        "received_at_ts": 2100.0,
        "sender": "b@example.com",
        "subject": "新邮件",
        "summary": "新邮件摘要",
        "attachments": ["a.docx"],
        "text": "标题：新邮件",
    }
    monkeypatch.setattr(mail_account_service.time, "time", lambda: 2000.0)
    with patch("src.platform.mail_account_service._fetch_recent_mail_items", return_value=[old_item]):
        run_mail_new_message_notifier(force=True)

    monkeypatch.setattr(mail_account_service.time, "time", lambda: 2100.0)
    sent: list[tuple[str, dict[str, object]]] = []
    with patch("src.platform.mail_account_service._fetch_recent_mail_items", return_value=[old_item, new_item]), \
         patch("src.platform.mail_account_service._send_mail_notification", side_effect=lambda account, item: sent.append((account["user_id"], item)) or True):
        result = run_mail_new_message_notifier(force=True)

    assert result["new_messages"] == 1
    assert result["sent"] == 1
    assert sent == [("u1", new_item)]


def test_mail_new_message_notification_only_announces_arrival() -> None:
    from src.platform.mail_account_service import _send_mail_notification

    sent: list[tuple[str, str, str]] = []

    account = {"platform": "wecom", "user_id": "u1", "email_address": "u1@example.com"}
    item = {
        "message_key": "new-1",
        "received_at": "Fri, 17 Jul 2026 08:30:00 +0800",
        "sender": "sender@example.com",
        "subject": "重要合同",
        "summary": "这是一段邮件正文摘要",
        "attachments": ["合同.docx"],
        "text": "邮件到达时间：Fri, 17 Jul 2026 08:30:00 +0800\n发件人：sender@example.com\n标题：重要合同\n摘要：这是一段邮件正文摘要\n附件：合同.docx",
    }

    with patch("src.gateway.provider_outbound.send_platform_text", side_effect=lambda p, u, t: sent.append((p, u, t)) or True):
        assert _send_mail_notification(account, item) is True

    assert sent
    text = sent[0][2]
    assert "【新邮件提醒】" in text
    assert "你有一封新邮件到达" in text
    assert "查看未读邮件" in text
    assert "sender@example.com" not in text
    assert "重要合同" not in text
    assert "这是一段邮件正文摘要" not in text
    assert "合同.docx" not in text
    assert "邮件到达时间" not in text


def test_mail_new_message_notifier_does_not_summarize_already_seen_messages(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "ant.db"))
    monkeypatch.setenv("ANT_COLONY_MAIL_FIRST_RUN_NOTIFY_SECONDS", "0")

    from src.platform import mail_account_service
    from src.platform.mail_account_service import save_mail_account, run_mail_new_message_notifier

    save_mail_account(
        {
            "platform": "wecom",
            "user_id": "u1",
            "email_address": "u1@example.com",
            "imap_host": "imap.example.com",
            "imap_port": 993,
            "protocol": "imap",
            "username": "u1@example.com",
            "password": "secret",
            "poll_interval_minutes": 1,
            "enabled": True,
        },
        updated_by="admin",
    )
    msg = email.message.EmailMessage()
    msg["From"] = "sender@example.com"
    msg["Subject"] = "重复邮件"
    msg["Date"] = "Fri, 17 Jul 2026 08:30:00 +0800"
    msg["Message-ID"] = "<same@example.com>"
    msg.set_content("这封邮件不应该重复摘要。")
    item = mail_account_service._mail_item_from_message(
        msg,
        account={"account_id": "mail-test"},
        fallback_key="same",
        raw=msg.as_bytes(),
        include_summary=False,
    )
    monkeypatch.setattr(mail_account_service.time, "time", lambda: 2000.0)
    with patch("src.platform.mail_account_service._fetch_recent_mail_items", return_value=[item]):
        run_mail_new_message_notifier(force=True)

    monkeypatch.setattr(mail_account_service.time, "time", lambda: 2100.0)
    with patch("src.platform.mail_account_service._fetch_recent_mail_items", return_value=[item]), \
         patch("src.platform.mail_account_service._summarize_text", side_effect=AssertionError("seen mail should not be summarized")):
        result = run_mail_new_message_notifier(force=True)

    assert result["new_messages"] == 0
    assert result["sent"] == 0


def test_mail_new_message_notifier_pop3_seen_messages_do_not_download_body(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "ant.db"))
    monkeypatch.setenv("ANT_COLONY_MAIL_FIRST_RUN_NOTIFY_SECONDS", "0")

    from src.platform import mail_account_service
    from src.platform.mail_account_service import save_mail_account, run_mail_new_message_notifier

    save_mail_account(
        {
            "platform": "wecom",
            "user_id": "u1",
            "email_address": "u1@example.com",
            "imap_host": "pop.example.com",
            "imap_port": 110,
            "protocol": "pop3",
            "encryption": "none",
            "username": "u1@example.com",
            "password": "secret",
            "poll_interval_minutes": 1,
            "enabled": True,
        },
        updated_by="admin",
    )
    header = email.message.EmailMessage()
    header["From"] = "sender@example.com"
    header["Subject"] = "POP3 重复邮件"
    header["Date"] = "Fri, 17 Jul 2026 08:30:00 +0800"
    header_lines = header.as_bytes().splitlines()
    fake_pop = MagicMock()
    fake_pop.list.return_value = (b"+OK", [b"1 123"], 123)
    fake_pop.uidl.return_value = (b"+OK", [b"1 uid-1"], 123)
    fake_pop.top.return_value = (b"+OK", header_lines, 123)
    fake_pop.retr.side_effect = AssertionError("seen POP3 mail should not be downloaded")

    monkeypatch.setattr(mail_account_service.time, "time", lambda: 2000.0)
    with patch("poplib.POP3", return_value=fake_pop):
        run_mail_new_message_notifier(force=True)

    monkeypatch.setattr(mail_account_service.time, "time", lambda: 2100.0)
    with patch("poplib.POP3", return_value=fake_pop):
        result = run_mail_new_message_notifier(force=True)

    assert result["new_messages"] == 0
    assert result["sent"] == 0
    fake_pop.retr.assert_not_called()


def test_mail_new_message_notifier_skips_users_without_active_assistant(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "ant.db"))

    from src.platform import mail_account_service
    from src.platform.mail_account_service import save_mail_account, run_mail_new_message_notifier

    save_mail_account(
        {
            "platform": "wecom",
            "user_id": "u1",
            "email_address": "u1@example.com",
            "imap_host": "imap.example.com",
            "imap_port": 993,
            "protocol": "imap",
            "username": "u1@example.com",
            "password": "secret",
            "enabled": True,
        },
        updated_by="admin",
    )
    monkeypatch.setattr(mail_account_service.time, "time", lambda: 2000.0)
    items = [
        {
            "message_key": "recent-1",
            "received_at": "recent",
            "received_at_ts": 1999.0,
            "sender": "a@example.com",
            "subject": "近期邮件",
            "summary": "近期邮件摘要",
            "attachments": [],
            "text": "标题：近期邮件",
        }
    ]

    with patch("src.platform.mail_account_service._fetch_recent_mail_items", return_value=items), \
         patch("src.platform.mail_account_service._send_mail_notification") as send:
        result = run_mail_new_message_notifier(force=True)

    assert result["no_active_ai_assistant"] == 1
    assert result["sent"] == 0
    send.assert_not_called()


def test_mail_new_message_notifier_skips_when_previous_run_lock_exists(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "ant.db"))
    lock_path = tmp_path / "mail.lock"
    lock_path.write_text("other-process", encoding="utf-8")
    monkeypatch.setenv("ANT_COLONY_MAIL_NOTIFIER_LOCK", str(lock_path))

    from src.platform.mail_account_service import run_mail_new_message_notifier

    with patch("src.platform.mail_account_service._run_mail_new_message_notifier_unlocked") as unlocked:
        result = run_mail_new_message_notifier(force=True)

    assert result["skipped_locked"] == 1
    assert "上一轮邮箱监听仍在运行" in result["message"]
    unlocked.assert_not_called()


def test_mail_new_message_notifier_clears_stale_lock(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "ant.db"))
    lock_path = tmp_path / "mail.lock"
    lock_path.write_text("dead-process", encoding="utf-8")
    old = 1000
    os.utime(lock_path, (old, old))
    monkeypatch.setenv("ANT_COLONY_MAIL_NOTIFIER_LOCK", str(lock_path))
    monkeypatch.setenv("ANT_COLONY_MAIL_NOTIFIER_LOCK_STALE_SECONDS", "120")

    from src.platform import mail_account_service
    from src.platform.mail_account_service import run_mail_new_message_notifier

    monkeypatch.setattr(mail_account_service.time, "time", lambda: 2000.0)
    with patch(
        "src.platform.mail_account_service._run_mail_new_message_notifier_unlocked",
        return_value={"sent": 0},
    ) as unlocked:
        result = run_mail_new_message_notifier(force=True)

    assert result == {"sent": 0}
    assert not lock_path.exists()
    unlocked.assert_called_once()


def test_mail_new_message_notifier_clears_dead_pid_lock_without_waiting(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "ant.db"))
    lock_path = tmp_path / "mail.lock"
    lock_path.write_text("999999999 2000", encoding="utf-8")
    monkeypatch.setenv("ANT_COLONY_MAIL_NOTIFIER_LOCK", str(lock_path))

    from src.platform import mail_account_service
    from src.platform.mail_account_service import run_mail_new_message_notifier

    monkeypatch.setattr(mail_account_service, "_process_is_alive", lambda _pid: False)
    with patch(
        "src.platform.mail_account_service._run_mail_new_message_notifier_unlocked",
        return_value={"sent": 0},
    ) as unlocked:
        result = run_mail_new_message_notifier(force=True)

    assert result == {"sent": 0}
    assert not lock_path.exists()
    unlocked.assert_called_once()


def test_missing_mailbox_configuration_does_not_require_imap(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "ant.db"))
    from src.platform.mail_account_service import summarize_user_mailbox

    result = summarize_user_mailbox("wecom", "not-configured")

    assert "当前企业 IM 账号尚未配置邮箱未读统计" in result
    assert "IMAP" not in result
    assert "接收协议" in result
    assert "不会共享" in result


def test_summarize_user_mailbox_uses_user_specific_imap_config(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "ant.db"))

    from src.platform.mail_account_service import save_mail_account, summarize_user_mailbox

    save_mail_account(
        {
            "platform": "wecom",
            "user_id": "u1",
            "email_address": "u1@example.com",
            "imap_host": "imap.example.com",
            "imap_port": 993,
            "protocol": "imap",
            "username": "u1@example.com",
            "password": "secret",
            "poll_interval_minutes": 5,
            "enabled": True,
        },
        updated_by="admin",
    )

    msg = email.message.EmailMessage()
    msg["From"] = "sender@example.com"
    msg["Subject"] = "设备巡检"
    msg["Date"] = "Fri, 17 Jul 2026 08:30:00 +0800"
    msg.set_content("请查看附件并确认本周设备巡检计划。正文第二句。")
    msg.add_attachment(b"abc", maintype="application", subtype="pdf", filename="plan.pdf")
    raw = msg.as_bytes()

    fake_imap = MagicMock()
    fake_imap.search.return_value = ("OK", [b"101"])
    fake_imap.uid.return_value = ("OK", [(b"101 (RFC822 {123}", raw)])

    with patch("imaplib.IMAP4_SSL", return_value=fake_imap) as imap_cls:
        result = summarize_user_mailbox("wecom", "u1", limit=3)

    imap_cls.assert_called_once_with("imap.example.com", 993)
    fake_imap.login.assert_called_once_with("u1@example.com", "secret")
    assert "当前有 1 封未读邮件" in result
    assert "邮件摘要功能已关闭" in result
    assert "邮件到达时间：" not in result
    assert "发件人：" not in result
    assert "标题：" not in result
    assert "摘要：" not in result
    assert "附件：" not in result
    fake_imap.uid.assert_not_called()
    assert "secret" not in result


def test_mail_query_reports_unread_count_without_fetching_body(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "ant.db"))

    from src.platform.mail_account_service import save_mail_account, summarize_user_mailbox

    save_mail_account(
        {
            "platform": "wecom",
            "user_id": "u1",
            "account_label": "工作邮箱",
            "email_address": "u1@example.com",
            "imap_host": "imap.example.com",
            "imap_port": 993,
            "protocol": "imap",
            "username": "u1@example.com",
            "password": "secret",
            "enabled": True,
        },
        updated_by="admin",
    )

    fake_imap = MagicMock()
    fake_imap.search.return_value = ("OK", [b"101 102 103"])
    fake_imap.uid.side_effect = AssertionError("unread count should not fetch mail body")

    with patch("imaplib.IMAP4_SSL", return_value=fake_imap):
        result = summarize_user_mailbox("wecom", "u1")

    fake_imap.search.assert_called_once_with(None, "UNSEEN")
    assert "来源邮箱：工作邮箱 <u1@example.com>" in result
    assert "当前有 3 封未读邮件" in result
    assert "邮件摘要功能已关闭" in result
    assert "发件人：" not in result
    assert "标题：" not in result
    assert "摘要：" not in result


def test_summarize_user_mailbox_supports_pop3(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "ant.db"))

    from src.platform.mail_account_service import save_mail_account, summarize_user_mailbox

    save_mail_account(
        {
            "platform": "wecom",
            "user_id": "u1",
            "email_address": "u1@example.com",
            "protocol": "pop3",
            "imap_host": "pop.example.com",
            "imap_port": 995,
            "username": "u1@example.com",
            "password": "secret",
            "enabled": True,
        },
        updated_by="admin",
    )

    msg = email.message.EmailMessage()
    msg["From"] = "boss@example.com"
    msg["Subject"] = "会议通知"
    msg["Date"] = "Fri, 17 Jul 2026 09:00:00 +0800"
    msg.set_content("下午三点开会，请准备材料。")
    raw_lines = msg.as_bytes().splitlines()

    fake_pop = MagicMock()
    fake_pop.list.return_value = (b"+OK", [b"1 123"], 123)
    fake_pop.retr.return_value = (b"+OK", raw_lines, 123)

    with patch("poplib.POP3_SSL", return_value=fake_pop) as pop_cls:
        result = summarize_user_mailbox("wecom", "u1", limit=5)

    pop_cls.assert_not_called()
    fake_pop.user.assert_not_called()
    fake_pop.pass_.assert_not_called()
    assert "POP3 协议不提供可靠未读状态" in result
    assert "如需查看未读数量" in result
    assert "发件人：" not in result
    assert "标题：" not in result


def test_mail_summary_uses_clean_body_not_signature_or_forward_headers(monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_MAIL_LLM_SUMMARY", "0")
    from src.platform.mail_account_service import _summarize_text

    body = """
Yu Lin 综合管理部 +86 18660060472 lin.yu@example.com
---- 转发的原邮件 ----
发件人<jiyun.chen@example.com>日期2026年6月30日 15:27收件人常英祥<yingxiang.chang@example.com>
请各部门在本周五前提交设备点检整改完成情况，并补充未完成事项的责任人和计划完成时间。
谢谢
"""

    result = _summarize_text(body)

    assert "设备点检整改完成情况" in result
    assert "Yu Lin" not in result
    assert "综合管理部" not in result
    assert "转发的原邮件" not in result
    assert "jiyun.chen" not in result


def test_mail_summary_skips_packed_contact_header_from_forwarded_mail(monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_MAIL_LLM_SUMMARY", "0")
    from src.platform.mail_account_service import _summarize_text

    body = """
Yu Lin 综合管理部 刘法义<fayi.liu@example.com>, 田加启<jiaqi.tian@example.com>, 宋得罗<deluo.song@example.com>, <bo.cui@example.com>, 'fei.xie'<fei.xie@example.com>, <haitao.sun@example.com>
---- 转发的原邮件 ----
发件人<jiyun.chen@example.com>日期2026年6月30日 15:27收件人常英祥<yingxiang.chang@example.com>, 刘法义<fayi.liu@example.com>
TUV莱茵监督审核安排如下：请各部门按审核计划准备质量体系文件、生产记录和现场审核材料，确认陪审人员并按时参加首次会议。
"""

    result = _summarize_text(body, subject="转发：TUV莱茵监督审核——审核计划")

    assert "TUV莱茵" in result or "审核" in result
    assert "Yu Lin" not in result
    assert "综合管理部" not in result
    assert "fayi.liu" not in result
    assert "发件人" not in result
    assert "转发的原邮件" not in result
    assert len(result) <= 120


def test_mail_summary_skips_multiline_forward_recipient_header(monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_MAIL_LLM_SUMMARY", "0")
    from src.platform.mail_account_service import _summarize_text

    body = """
Yu Lin
综合管理部
+86 18660060472
lin.yu@example.com
---- 转发的原邮件 ----
发件人<jiyun.chen@example.com>日期2026年6月30日 15:27收件人常英祥<yingxiang.chang@example.com>,
刘法义<fayi.liu@example.com>,
田加启<jiaqi.tian@example.com>,
宋得罗<deluo.song@example.com>,
<bo.cui@example.com>,
'fei.xie'<fei.xie@example.com>,
qagma<qagma@deyuaninv.com>主题TUV莱茵监督审核——审核计划
各位领导：
下午好！
附件为本次TUV莱茵监督审核计划，请各部门按计划准备审核资料并安排相关人员参加。
"""

    result = _summarize_text(body, subject="转发：TUV莱茵监督审核——审核计划")

    assert "TUV莱茵监督审核" in result
    assert "Yu Lin" not in result
    assert "综合管理部" not in result
    assert "fayi.liu" not in result
    assert "qagma" not in result
    assert "发件人" not in result
    assert len(result) <= 120


def test_mail_summary_local_fallback_is_concise_not_body_copy(monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_MAIL_LLM_SUMMARY", "0")
    from src.platform.mail_account_service import _summarize_text

    result = _summarize_text(
        "各位领导：\n下午好！\n附件为本次TUV莱茵监督审核的审核计划，请查阅！并对照做好相应准备。",
        subject="转发：TUV莱茵监督审核——审核计划",
    )

    assert "TUV莱茵监督审核" in result
    assert "各位领导" not in result
    assert "下午好" not in result
    assert len(result) <= 120


def test_mail_summary_skips_mojibake_forward_separator(monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_MAIL_LLM_SUMMARY", "0")
    from src.platform.mail_account_service import _summarize_text

    body = """
---- ???????????????????????????????????????????? ----
TUV audit plan: Please prepare quality records and confirm attendees before the supervision audit.
"""

    result = _summarize_text(body)

    assert "??????????????????????" not in result
    assert "TUV audit plan" in result


def test_mail_summary_sends_cleaned_body_to_llm(monkeypatch) -> None:
    from src.platform import mail_account_service

    class FakeProfile:
        enabled = True
        api_key = "key"
        model_name = "model"
        provider = "openai"
        api_base = ""
        max_tokens = 4096
        metadata = {"is_default": True}

    class FakeSettings:
        def build_runtime_snapshot(self):
            return type("Snapshot", (), {"llm_profiles": [FakeProfile()]})()

    seen = {}

    def fake_call(profile, *, text, subject="", sender=""):
        seen["text"] = text
        return "通知各部门准备TUV监督审核资料，确认陪审人员并按时参加首次会议。"

    monkeypatch.setattr("src.config.bootstrap.build_settings_service", lambda: FakeSettings())
    monkeypatch.setattr(mail_account_service, "_call_mail_summary_profile", fake_call)

    result = mail_account_service._summarize_text(
        """
Yu Lin 综合管理部 刘法义<fayi.liu@example.com>, 田加启<jiaqi.tian@example.com>
---- 转发的原邮件 ----
发件人<jiyun.chen@example.com>日期2026年6月30日 15:27收件人常英祥<yingxiang.chang@example.com>
TUV莱茵监督审核安排如下：请各部门按审核计划准备质量体系文件、生产记录和现场审核材料。
""",
        subject="转发：TUV莱茵监督审核——审核计划",
    )

    assert result == "通知各部门准备TUV监督审核资料，确认陪审人员并按时参加首次会议。"
    assert "TUV莱茵监督审核" in seen["text"]
    assert "Yu Lin" not in seen["text"]
    assert "fayi.liu" not in seen["text"]
    assert "发件人" not in seen["text"]


def test_mail_summary_can_use_llm_for_short_body_summary(monkeypatch) -> None:
    from src.platform import mail_account_service

    class FakeProfile:
        enabled = True
        api_key = "key"
        model_name = "model"
        provider = "openai"
        api_base = ""
        max_tokens = 4096
        metadata = {"is_default": True}

    class FakeSettings:
        def build_runtime_snapshot(self):
            return type("Snapshot", (), {"llm_profiles": [FakeProfile()]})()

    monkeypatch.setattr("src.config.bootstrap.build_settings_service", lambda: FakeSettings())
    monkeypatch.setattr(
        mail_account_service,
        "_call_mail_summary_profile",
        lambda profile, *, text, subject="", sender="": "要求各部门本周五前提交设备点检整改完成情况，并说明责任人与计划时间。",
    )

    result = mail_account_service._summarize_text(
        "请各部门在本周五前提交设备点检整改完成情况，并补充未完成事项的责任人和计划完成时间。"
    )

    assert result == "要求各部门本周五前提交设备点检整改完成情况，并说明责任人与计划时间。"


def test_mail_summary_tries_next_model_when_default_profile_fails(monkeypatch) -> None:
    from src.platform import mail_account_service

    class FakeProfile:
        def __init__(self, profile_id: str, *, is_default: bool = False):
            self.profile_id = profile_id
            self.enabled = True
            self.api_key = "key"
            self.model_name = profile_id
            self.provider = "openai"
            self.api_base = ""
            self.max_tokens = 4096
            self.metadata = {"is_default": is_default}

    class FakeSettings:
        def build_runtime_snapshot(self):
            return type("Snapshot", (), {"llm_profiles": [FakeProfile("bad", is_default=True), FakeProfile("good")]})()

    calls = []

    def fake_call(profile, *, text, subject="", sender=""):
        calls.append(profile.profile_id)
        if profile.profile_id == "bad":
            raise RuntimeError("unsupported model")
        return "已用可用模型生成正文摘要。"

    monkeypatch.setattr("src.config.bootstrap.build_settings_service", lambda: FakeSettings())
    monkeypatch.setattr(mail_account_service, "_call_mail_summary_profile", fake_call)

    result = mail_account_service._summarize_text("正文内容")

    assert result == "已用可用模型生成正文摘要。"
    assert calls == ["bad", "good"]


def test_mail_summary_profile_normalizes_opencode_model_for_zen_api(monkeypatch) -> None:
    from src.platform.mail_account_service import _call_mail_summary_profile

    seen = {}

    class FakeCompletions:
        def create(self, **kwargs):
            seen.update(kwargs)
            return type(
                "Response",
                (),
                {"choices": [type("Choice", (), {"message": type("Message", (), {"content": "正文摘要"})()})()]},
            )()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            seen["client_kwargs"] = kwargs
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    profile = type(
        "Profile",
        (),
        {
            "provider": "openai_compatible",
            "model_name": "opencode/deepseek-v4-flash-free",
            "api_key": "key",
            "api_base": "https://opencode.ai/zen/v1",
        },
    )()
    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)

    result = _call_mail_summary_profile(profile, text="正文内容")

    assert result == "正文摘要"
    assert seen["model"] == "deepseek-v4-flash-free"


def test_pop3_plain_connection_does_not_force_ssl(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "pop3-plain.db"))
    from src.platform.mail_account_service import save_mail_account, summarize_user_mailbox

    save_mail_account(
        {
            "platform": "wecom", "user_id": "u-pop3", "email_address": "u@example.com",
            "protocol": "pop3", "imap_host": "pop.example.com", "imap_port": 110,
            "encryption": "none", "username": "u@example.com", "password": "secret",
        }
    )
    client = MagicMock()
    client.list.return_value = (b"+OK", [], 0)
    with patch("src.platform.mail_account_service.poplib.POP3", return_value=client) as plain, \
         patch("src.platform.mail_account_service.poplib.POP3_SSL") as ssl:
        result = summarize_user_mailbox("wecom", "u-pop3")

    assert "来源邮箱：默认邮箱 <u@example.com>" in result
    assert "POP3 协议不提供可靠未读状态" in result
    plain.assert_not_called()
    ssl.assert_not_called()


def test_pop3_starttls_upgrades_before_login(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "pop3-starttls.db"))
    from src.platform.mail_account_service import save_mail_account, summarize_user_mailbox

    save_mail_account(
        {
            "platform": "wecom", "user_id": "u-starttls", "email_address": "u@example.com",
            "protocol": "pop3", "imap_host": "pop.example.com", "imap_port": 110,
            "encryption": "starttls", "username": "u@example.com", "password": "secret",
        }
    )
    client = MagicMock()
    client.list.return_value = (b"+OK", [], 0)
    with patch("src.platform.mail_account_service.poplib.POP3", return_value=client):
        result = summarize_user_mailbox("wecom", "u-starttls")

    assert "来源邮箱：默认邮箱 <u@example.com>" in result
    assert "POP3 协议不提供可靠未读状态" in result
    client.stls.assert_not_called()


def test_pop3_login_passerr_returns_actionable_message(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "pop3-passerr.db"))
    from src.platform.mail_account_service import save_mail_account, summarize_mail_account

    account = save_mail_account(
        {
            "platform": "wecom",
            "user_id": "u1",
            "account_label": "招聘",
            "email_address": "hr@example.com",
            "protocol": "pop3",
            "imap_host": "pop.example.com",
            "imap_port": 110,
            "encryption": "none",
            "username": "hr@example.com",
            "password": "wrong-secret",
        }
    )
    client = MagicMock()
    client.pass_.side_effect = Exception("b'-ERR ERR.LOGIN.PASSERR'")
    with patch("src.platform.mail_account_service.poplib.POP3", return_value=client) as pop_cls:
        result = summarize_mail_account(account["account_id"])

    assert "来源邮箱：招聘 <hr@example.com>" in result
    assert "POP3 协议不提供可靠未读状态" in result
    pop_cls.assert_not_called()
    assert "wrong-secret" not in result


def test_mail_account_diagnosis_identifies_bad_netease_auth_code(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "mail-diagnosis.db"))
    from src.platform.mail_account_service import diagnose_mail_account_connection, save_mail_account

    account = save_mail_account(
        {
            "platform": "wecom",
            "user_id": "u1",
            "account_label": "默认邮箱",
            "email_address": "xiaolin.zhang@example.com",
            "protocol": "pop3",
            "imap_host": "pophz.qiye.163.com",
            "imap_port": 110,
            "encryption": "none",
            "username": "xiaolin.zhang@example.com",
            "password": "saved-secret",
        }
    )

    class FakePOP3:
        def __init__(self, *_args, **_kwargs):
            self.username = ""

        def user(self, username):
            self.username = username

        def pass_(self, _password):
            if "@" in self.username:
                raise Exception("b'-ERR ERR.LOGIN.PASSERR'")
            raise Exception("b'-ERR ERR.ILLEGAL.EMAIL'")

        def quit(self):
            return None

    class FakeIMAP:
        def __init__(self, *_args, **_kwargs):
            return None

        def login(self, username, _password):
            if "@" in username:
                raise Exception("b'-ERR ERR.LOGIN.PASSERR'")
            raise Exception("b'-ERR ERR.ILLEGAL.EMAIL'")

        def logout(self):
            return None

    with patch("src.platform.mail_account_service.poplib.POP3", FakePOP3), \
         patch("src.platform.mail_account_service.poplib.POP3_SSL", FakePOP3), \
         patch("src.platform.mail_account_service.imaplib.IMAP4", FakeIMAP), \
         patch("src.platform.mail_account_service.imaplib.IMAP4_SSL", FakeIMAP):
        result = diagnose_mail_account_connection(account["account_id"])

    assert "完整邮箱账号均被服务端拒绝" in result
    assert "邮箱前缀账号被服务端判定为非法账号" in result
    assert "网页端密码正确不等于 POP3/IMAP 客户端协议可登录" in result
    assert "开启 POP3/IMAP/SMTP 客户端登录" in result
    assert "saved-secret" not in result


def test_mail_account_diagnosis_reports_current_configuration_login_ok(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "mail-diagnosis-ok.db"))
    from src.platform.mail_account_service import diagnose_mail_account_connection, save_mail_account

    account = save_mail_account(
        {
            "platform": "wecom",
            "user_id": "u1",
            "email_address": "xiaolin.zhang@example.com",
            "protocol": "pop3",
            "imap_host": "pophz.qiye.163.com",
            "imap_port": 110,
            "encryption": "none",
            "username": "xiaolin.zhang@example.com",
            "password": "saved-secret",
        }
    )

    client = MagicMock()
    with patch("src.platform.mail_account_service.poplib.POP3", return_value=client):
        result = diagnose_mail_account_connection(account["account_id"])

    assert "当前后台保存的邮箱配置和密码/授权码已经可以通过客户端协议登录" in result
    assert "配置的协议、服务器、端口、加密方式或账号写法不匹配" not in result
    assert "saved-secret" not in result


def test_exchange_protocol_returns_actionable_configuration_message(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "ant.db"))

    from src.platform.mail_account_service import save_mail_account, summarize_user_mailbox

    save_mail_account(
        {
            "platform": "wecom",
            "user_id": "u1",
            "email_address": "u1@example.com",
            "protocol": "exchange",
            "imap_host": "exchange.example.com",
            "username": "u1@example.com",
            "password": "secret",
        },
        updated_by="admin",
    )

    result = summarize_user_mailbox("wecom", "u1")

    assert "Exchange 邮箱" in result
    assert "secret" not in result


def test_internal_mail_summary_uses_capability_context_user(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "ant.db"))

    from src.platform.capability_audit import CapabilityInvocationContext
    from src.platform.internal_capability_provider import InternalCapabilityProvider

    ctx = CapabilityInvocationContext(user_id="u1", platform="wecom")
    with patch("src.platform.mail_account_service.summarize_user_mailbox", return_value="user mail") as summarize:
        result = InternalCapabilityProvider().summarize_mailbox("", capability_context=ctx)

    assert result == "user mail"
    summarize.assert_called_once_with("wecom", "u1", query="", limit=10)
