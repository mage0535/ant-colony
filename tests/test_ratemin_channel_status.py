from __future__ import annotations

import time
from unittest.mock import patch


def _reset_db(db_path: str) -> None:
    from src.store.database import Database

    Database.get(db_path).close()
    Database._instances.pop(db_path, None)  # type: ignore[attr-defined]


def test_ratemin_channel_status_reports_healthy_channel(tmp_path) -> None:
    from src.platform.ratemin_collector_health import get_ratemin_channel_status
    from src.platform.ratemin_service import sync_ratemin_current_events

    db_path = str(tmp_path / "ratemin-channel-healthy.db")
    with patch.dict(
        "os.environ",
        {"ANT_COLONY_DB_PATH": db_path, "RATEMIN_COLLECTOR_MAX_STALE_SECONDS": "300", "RATEMIN_COLLECTOR_ALERT_USER_IDS": ""},
        clear=False,
    ):
        _reset_db(db_path)
        sync_ratemin_current_events(
            [{"source_db": "business_a", "flow_id": "1", "flow_post_id": "2", "data_id": "3", "task_id": "4", "recipient_oper_id": "298"}],
            source_databases=["business_a"],
        )
        result = get_ratemin_channel_status(platform="wecom")

    assert result["overall_status"] == "healthy"
    assert result["problem_origin"] == "none"
    assert result["ratemin_server"]["status"] == "healthy"
    assert result["project_server"]["status"] == "healthy"
    assert result["manual_steps"]["project_server"]
    assert result["manual_steps"]["ratemin_server"]


def test_ratemin_channel_status_identifies_project_server_failure(tmp_path) -> None:
    from src.platform.ratemin_collector_health import get_ratemin_channel_status
    from src.platform.ratemin_service import ingest_ratemin_events, sync_ratemin_current_events
    from src.store.database import Database

    db_path = str(tmp_path / "ratemin-channel-project-failure.db")
    with patch.dict(
        "os.environ",
        {"ANT_COLONY_DB_PATH": db_path, "RATEMIN_COLLECTOR_MAX_STALE_SECONDS": "300", "RATEMIN_COLLECTOR_ALERT_USER_IDS": ""},
        clear=False,
    ):
        _reset_db(db_path)
        event = {"source_db": "business_a", "flow_id": "1", "flow_post_id": "2", "data_id": "3", "task_id": "4", "recipient_oper_id": "298"}
        sync_ratemin_current_events([event], source_databases=["business_a"])
        ingest_ratemin_events([event], platform="wecom")
        conn = Database.get(db_path).connect()
        conn.execute("UPDATE ratemin_pending_events SET delivery_status = 'send_failed'")
        conn.commit()
        result = get_ratemin_channel_status(platform="wecom")

    assert result["overall_status"] == "unhealthy"
    assert result["problem_origin"] == "project_server"
    assert result["project_server"]["failed_count"] == 1


def test_ratemin_channel_status_keeps_ready_queue_as_degraded(tmp_path) -> None:
    from src.platform.ratemin_collector_health import get_ratemin_channel_status
    from src.platform.ratemin_service import ingest_ratemin_events, sync_ratemin_current_events
    from src.store.database import Database

    db_path = str(tmp_path / "ratemin-channel-ready-queue.db")
    with patch.dict(
        "os.environ",
        {"ANT_COLONY_DB_PATH": db_path, "RATEMIN_COLLECTOR_MAX_STALE_SECONDS": "300", "RATEMIN_COLLECTOR_ALERT_USER_IDS": ""},
        clear=False,
    ):
        _reset_db(db_path)
        event = {"source_db": "business_a", "flow_id": "1", "flow_post_id": "2", "data_id": "3", "task_id": "4", "recipient_oper_id": "298"}
        sync_ratemin_current_events([event], source_databases=["business_a"])
        ingest_ratemin_events([event], platform="wecom")
        conn = Database.get(db_path).connect()
        conn.execute("UPDATE ratemin_pending_events SET delivery_status = 'ready'")
        conn.commit()
        result = get_ratemin_channel_status(platform="wecom")

    assert result["overall_status"] == "degraded"
    assert result["problem_origin"] == "project_server"
    assert result["project_server"]["ready_count"] == 1


def test_recover_ratemin_channel_runs_wake_and_pending_flush(tmp_path) -> None:
    from src.platform.ratemin_collector_health import recover_ratemin_channel
    from src.platform.ratemin_service import sync_ratemin_current_events
    from src.store.database import Database

    db_path = str(tmp_path / "ratemin-channel-recover.db")
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

        result = recover_ratemin_channel(platform="wecom")

    assert result["collector_recovery"]["wake_attempted"] is True
    assert result["collector_recovery"]["wake_status"] == "ok"
    assert result["project_recovery"]["failed"] == 0
    assert "status_after_recovery" in result
