from __future__ import annotations

import json
import time
from unittest.mock import patch


def _reset_db(db_path: str) -> None:
    from src.store.database import Database

    Database.get(db_path).close()
    Database._instances.pop(db_path, None)  # type: ignore[attr-defined]


def test_ratemin_collector_health_reports_healthy_when_snapshot_is_fresh(tmp_path) -> None:
    from src.platform.ratemin_collector_health import check_ratemin_collector_health
    from src.platform.ratemin_service import sync_ratemin_current_events

    db_path = str(tmp_path / "ratemin-health.db")
    with patch.dict(
        "os.environ",
        {"ANT_COLONY_DB_PATH": db_path, "RATEMIN_COLLECTOR_MAX_STALE_SECONDS": "300", "RATEMIN_COLLECTOR_ALERT_USER_IDS": ""},
        clear=False,
    ):
        _reset_db(db_path)
        sync_ratemin_current_events(
            [
                {
                    "source_db": "business_a",
                    "flow_id": "1",
                    "flow_post_id": "2",
                    "data_id": "3",
                    "task_id": "4",
                    "recipient_oper_id": "298",
                }
            ],
            source_databases=["business_a"],
        )
        result = check_ratemin_collector_health(wake=True)

    assert result["healthy"] is True
    assert result["wake_attempted"] is False


def test_ratemin_collector_health_runs_wake_command_when_stale(tmp_path) -> None:
    from src.platform.ratemin_collector_health import check_ratemin_collector_health
    from src.platform.ratemin_service import sync_ratemin_current_events
    from src.store.database import Database

    db_path = str(tmp_path / "ratemin-health-stale.db")
    with patch.dict(
        "os.environ",
        {
            "ANT_COLONY_DB_PATH": db_path,
            "RATEMIN_COLLECTOR_MAX_STALE_SECONDS": "30",
            "RATEMIN_COLLECTOR_WAKE_COMMAND": "wake-ratemin",
            "RATEMIN_COLLECTOR_ALERT_USER_IDS": "",
        },
        clear=False,
    ), patch("src.platform.ratemin_collector_health.subprocess.run") as run:
        _reset_db(db_path)
        sync_ratemin_current_events(
            [{"source_db": "business_a", "flow_id": "1", "flow_post_id": "2", "data_id": "3", "task_id": "4", "recipient_oper_id": "298"}],
            source_databases=["business_a"],
        )
        conn = Database.get(db_path).connect()
        conn.execute("UPDATE ratemin_current_events SET updated_at = ?", (time.time() - 999,))
        conn.commit()
        run.return_value.returncode = 0
        run.return_value.stdout = "started"
        run.return_value.stderr = ""
        result = check_ratemin_collector_health(wake=True)

    assert result["healthy"] is False
    assert result["wake_attempted"] is True
    assert result["wake_status"] == "ok"
    run.assert_called_once()
    assert run.call_args.kwargs["shell"] is False
    assert run.call_args.args[0] == ["wake-ratemin"]


def test_ratemin_collector_health_requires_explicit_shell_for_wake_command(tmp_path) -> None:
    from src.platform.ratemin_collector_health import check_ratemin_collector_health
    from src.platform.ratemin_service import sync_ratemin_current_events
    from src.store.database import Database

    db_path = str(tmp_path / "ratemin-health-shell.db")
    with patch.dict(
        "os.environ",
        {
            "ANT_COLONY_DB_PATH": db_path,
            "RATEMIN_COLLECTOR_MAX_STALE_SECONDS": "30",
            "RATEMIN_COLLECTOR_WAKE_COMMAND": "wake-ratemin && echo ok",
            "RATEMIN_COLLECTOR_WAKE_SHELL": "true",
            "RATEMIN_COLLECTOR_ALERT_USER_IDS": "",
        },
        clear=False,
    ), patch("src.platform.ratemin_collector_health.subprocess.run") as run:
        _reset_db(db_path)
        sync_ratemin_current_events(
            [{"source_db": "business_a", "flow_id": "1", "flow_post_id": "2", "data_id": "3", "task_id": "4", "recipient_oper_id": "298"}],
            source_databases=["business_a"],
        )
        conn = Database.get(db_path).connect()
        conn.execute("UPDATE ratemin_current_events SET updated_at = ?", (time.time() - 999,))
        conn.commit()
        run.return_value.returncode = 0
        run.return_value.stdout = "started"
        run.return_value.stderr = ""
        result = check_ratemin_collector_health(wake=True)

    assert result["wake_status"] == "ok"
    assert run.call_args.kwargs["shell"] is True
    assert run.call_args.args[0] == "wake-ratemin && echo ok"


def test_ratemin_collector_health_cron_entrypoint_returns_json(tmp_path) -> None:
    from src.platform.ratemin_collector_health import run_ratemin_collector_health_check

    db_path = str(tmp_path / "ratemin-health-empty.db")
    with patch.dict("os.environ", {"ANT_COLONY_DB_PATH": db_path, "RATEMIN_COLLECTOR_ALERT_USER_IDS": ""}, clear=False):
        _reset_db(db_path)
        payload = json.loads(run_ratemin_collector_health_check())

    assert payload["healthy"] is False
    assert payload["wake_status"] == "not_configured"


def test_ratemin_collector_health_alerts_once_when_stale(tmp_path) -> None:
    from src.platform.ratemin_collector_health import check_ratemin_collector_health
    from src.platform.ratemin_service import sync_ratemin_current_events
    from src.store.database import Database

    db_path = str(tmp_path / "ratemin-health-alert.db")
    sent: list[tuple[str, str, str]] = []
    with patch.dict(
        "os.environ",
        {
            "ANT_COLONY_DB_PATH": db_path,
            "RATEMIN_COLLECTOR_MAX_STALE_SECONDS": "30",
            "RATEMIN_COLLECTOR_ALERT_USER_IDS": "AdminUser",
            "RATEMIN_COLLECTOR_ALERT_MIN_INTERVAL_SECONDS": "600",
        },
        clear=False,
    ), patch(
        "src.platform.ratemin_collector_health.provider_outbound.send_platform_text",
        side_effect=lambda platform, user_id, text: sent.append((platform, user_id, text)) or True,
    ):
        _reset_db(db_path)
        sync_ratemin_current_events(
            [{"source_db": "business_a", "flow_id": "1", "flow_post_id": "2", "data_id": "3", "task_id": "4", "recipient_oper_id": "298"}],
            source_databases=["business_a"],
        )
        conn = Database.get(db_path).connect()
        conn.execute("UPDATE ratemin_current_events SET updated_at = ?", (time.time() - 999,))
        conn.commit()

        first = check_ratemin_collector_health(wake=True)
        second = check_ratemin_collector_health(wake=True)

    assert first["alert_status"] == "sent"
    assert second["alert_status"] == "throttled"
    assert len(sent) == 1
    assert sent[0][0] == "wecom"
    assert sent[0][1] == "AdminUser"
    assert "业务系统采集器异常" in sent[0][2]


def test_ratemin_collector_health_sends_recovery_after_unhealthy(tmp_path) -> None:
    from src.platform.ratemin_collector_health import check_ratemin_collector_health
    from src.platform.ratemin_service import sync_ratemin_current_events
    from src.store.database import Database

    db_path = str(tmp_path / "ratemin-health-recovery.db")
    sent: list[str] = []
    with patch.dict(
        "os.environ",
        {
            "ANT_COLONY_DB_PATH": db_path,
            "RATEMIN_COLLECTOR_MAX_STALE_SECONDS": "30",
            "RATEMIN_COLLECTOR_ALERT_USER_IDS": "AdminUser",
        },
        clear=False,
    ), patch(
        "src.platform.ratemin_collector_health.provider_outbound.send_platform_text",
        side_effect=lambda _platform, _user_id, text: sent.append(text) or True,
    ):
        _reset_db(db_path)
        sync_ratemin_current_events(
            [{"source_db": "business_a", "flow_id": "1", "flow_post_id": "2", "data_id": "3", "task_id": "4", "recipient_oper_id": "298"}],
            source_databases=["business_a"],
        )
        conn = Database.get(db_path).connect()
        conn.execute("UPDATE ratemin_current_events SET updated_at = ?", (time.time() - 999,))
        conn.commit()
        unhealthy = check_ratemin_collector_health(wake=True)

        conn.execute("UPDATE ratemin_current_events SET updated_at = ?", (time.time(),))
        conn.commit()
        recovered = check_ratemin_collector_health(wake=True)

    assert unhealthy["alert_status"] == "sent"
    assert recovered["alert_status"] == "recovery_sent"
    assert len(sent) == 2
    assert "业务系统采集器恢复" in sent[1]
