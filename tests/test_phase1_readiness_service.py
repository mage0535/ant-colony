from __future__ import annotations

from unittest.mock import patch


def test_phase1_readiness_reports_real_local_backends(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "ant.db"))
    for key in ("WECOM_CORP_ID", "WECOM_AGENT_ID", "WECOM_SECRET", "WECOM_APPROVAL_SECRET"):
        monkeypatch.delenv(key, raising=False)

    from src.platform.mail_account_service import save_mail_account
    from src.platform.phase1_readiness_service import collect_phase1_readiness
    from src.store.database import Database

    conn = Database.get().connect()
    conn.execute(
        "INSERT INTO org_users(platform,user_id,name,email,mobile,title) VALUES(?,?,?,?,?,?)",
        ("wecom", "u1", "Alice", "alice@example.com", "13800000000", "Engineer"),
    )
    conn.execute(
        "INSERT INTO knowledge_items(id,owner_type,owner_id,content,tags) VALUES(?,?,?,?,?)",
        ("k1", "organization", "*", "company guide", "[]"),
    )
    conn.execute(
        "INSERT INTO tasks(id,title,project_id,status) VALUES(?,?,?,?)",
        ("t1", "follow up", "default", "todo"),
    )
    conn.commit()
    save_mail_account(
        {
            "platform": "wecom",
            "user_id": "u1",
            "email_address": "alice@example.com",
            "protocol": "imap",
            "imap_host": "imap.example.com",
            "username": "alice@example.com",
            "password": "secret",
            "enabled": True,
        }
    )

    with patch("src.platform.phase1_readiness_service.os.path.isfile", return_value=True):
        report = collect_phase1_readiness(platform="wecom", user_id="u1")

    assert report["overall_status"] == "degraded"
    assert report["items"]["contacts"]["status"] == "ready"
    assert report["items"]["knowledge"]["status"] == "ready"
    assert report["items"]["tasks"]["status"] == "ready"
    assert report["items"]["mail"]["status"] == "ready"
    assert report["items"]["mail"]["metrics"]["configured_accounts"] == 1
    assert "secret" not in str(report)


def test_phase1_readiness_marks_mail_needs_configuration(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(tmp_path / "ant.db"))

    from src.platform.phase1_readiness_service import collect_phase1_readiness

    report = collect_phase1_readiness(platform="wecom", user_id="u2")

    assert report["items"]["mail"]["status"] == "needs_config"
    assert "管理员后台" in report["items"]["mail"]["next_action"]


def test_admin_phase1_readiness_endpoint_requires_admin_context() -> None:
    from src.web.dashboard import admin_phase1_readiness

    with patch("src.web.dashboard.require_admin_context_from_request", return_value={"platform": "wecom", "user_id": "admin"}), patch(
        "src.platform.phase1_readiness_service.collect_phase1_readiness",
        return_value={"overall_status": "ready", "items": {}},
    ) as collect:
        result = admin_phase1_readiness(object())

    assert result["overall_status"] == "ready"
    collect.assert_called_once_with(platform="wecom", user_id="admin")
