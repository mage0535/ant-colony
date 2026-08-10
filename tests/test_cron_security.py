from __future__ import annotations

from datetime import datetime
import urllib.error
from unittest.mock import patch

from src.orchestrator.cron_job import _parse_schedule, cron_result_status, run_no_agent
from src.orchestrator.cron_scheduler import _health_check, _org_sync, _register_defaults
from src.tools.dept_tool import query_subordinate_balance


def test_empty_schedule_falls_back_without_crashing() -> None:
    assert _parse_schedule("", base=1000.0) == 4600.0


def test_compact_interval_schedule_is_supported() -> None:
    assert _parse_schedule("every 2h", base=1000.0) == 8200.0


def test_cron_schedule_honors_month_field() -> None:
    base = datetime(2025, 12, 31, 23, 59).timestamp()

    result = _parse_schedule("0 0 1 2 *", base=base)

    assert result == datetime(2026, 2, 1, 0, 0).timestamp()


def test_cron_schedule_honors_weekday_field() -> None:
    base = datetime(2026, 1, 2, 10, 0).timestamp()  # Friday

    result = _parse_schedule("0 9 * * 1", base=base)

    assert result == datetime(2026, 1, 5, 9, 0).timestamp()  # Monday


def test_no_agent_jobs_reject_shell_commands() -> None:
    with patch("subprocess.run", side_effect=AssertionError("shell execution is forbidden")) as run:
        result = run_no_agent("echo unsafe")

    assert result == "REJECTED: command is not an allowed internal cron callable"
    run.assert_not_called()


def test_no_agent_jobs_reject_unknown_python_callables() -> None:
    result = run_no_agent("python:os.getcwd")

    assert result == "REJECTED: command is not an allowed internal cron callable"


def test_cron_result_status_does_not_mark_rejected_or_unimplemented_as_ok() -> None:
    assert cron_result_status("REJECTED: command is not an allowed internal cron callable").startswith("REJECTED")
    assert cron_result_status("EXCEPTION: boom").startswith("EXCEPTION")
    assert cron_result_status("(agent mode not yet implemented)").startswith("REJECTED")
    assert cron_result_status("normal result") == "OK"


def test_default_cron_jobs_use_allowed_internal_callables(tmp_path) -> None:
    from src.orchestrator.cron_job import CronJobRegistry

    registry = CronJobRegistry(str(tmp_path / "cron.json"))
    _register_defaults(registry)

    assert {job.command for job in registry.list()} == {
        "python:src.orchestrator.cron_scheduler._health_check",
        "python:src.orchestrator.cron_scheduler._org_sync",
        "python:src.platform.process_change_notifier.run_process_change_notifier",
        "python:src.platform.leave_quota_service.run_realtime_leave_sync",
        "python:src.platform.daily_brief_service.run_daily_briefs",
        "python:src.platform.mail_account_service.run_mail_new_message_notifier",
        "python:src.platform.public_data_service.run_public_data_subscriptions",
        "python:src.platform.ratemin_service.run_ratemin_pending_notifier",
        "python:src.platform.ratemin_collector_health.run_ratemin_collector_health_check",
    }


def test_default_cron_jobs_migrate_legacy_shell_commands(tmp_path) -> None:
    from src.orchestrator.cron_job import CronJob, CronJobRegistry

    registry = CronJobRegistry(str(tmp_path / "cron.json"))
    registry.register(
        CronJob(
            id="org-sync",
            name="组织架构同步",
            schedule="0 3 * * *",
            command="curl -X POST http://localhost:18092/api/v1/org/sync",
            tags=["system", "org"],
        )
    )

    _register_defaults(registry)

    assert registry.get("org-sync").command == "python:src.orchestrator.cron_scheduler._org_sync"


def test_daily_brief_is_disabled_by_default_and_on_existing_registry(tmp_path) -> None:
    from src.orchestrator.cron_job import CronJob, CronJobRegistry

    registry = CronJobRegistry(str(tmp_path / "cron.json"))
    registry.register(
        CronJob(
            id="daily-personal-brief",
            name="员工每日工作简报",
            schedule="every 30 min",
            command="python:src.platform.daily_brief_service.run_daily_briefs",
            enabled=True,
        )
    )

    _register_defaults(registry)

    job = registry.get("daily-personal-brief")
    assert job is not None
    assert job.enabled is False
    assert "不主动推送" in job.last_status


def test_mail_notifier_existing_schedule_migrates_to_one_minute(tmp_path) -> None:
    from src.orchestrator.cron_job import CronJob, CronJobRegistry

    registry = CronJobRegistry(str(tmp_path / "cron.json"))
    registry.register(
        CronJob(
            id="mail-new-message-notifier",
            name="企业邮箱新邮件提醒",
            schedule="every 5 min",
            command="python:src.platform.mail_account_service.run_mail_new_message_notifier",
            enabled=True,
        )
    )

    _register_defaults(registry)

    job = registry.get("mail-new-message-notifier")
    assert job is not None
    assert job.schedule == "every 1 min"
    assert "1 分钟" in job.last_status


def test_cron_registry_restores_persisted_run_state(tmp_path) -> None:
    from src.orchestrator.cron_job import CronJob, CronJobRegistry

    path = tmp_path / "cron.json"
    registry = CronJobRegistry(str(path))
    job = CronJob(
        id="health-check",
        name="系统健康检查",
        schedule="every 30 min",
        command="python:src.orchestrator.cron_scheduler._health_check",
        last_run=123.0,
        next_run=456.0,
        run_count=7,
        last_status="OK",
    )
    registry._jobs[job.id] = job
    registry._save()

    restored = CronJobRegistry(str(path)).get(job.id)

    assert restored is not None
    assert (restored.last_run, restored.next_run, restored.run_count, restored.last_status) == (
        123.0,
        456.0,
        7,
        "OK",
    )


def test_health_check_does_not_use_a_shell() -> None:
    completed = type("Completed", (), {"returncode": 0})()
    with patch("src.orchestrator.cron_scheduler.subprocess.run", return_value=completed) as run:
        _health_check()

    assert run.call_count == 6
    for call in run.call_args_list:
        assert call.args[0][:2] == ["systemctl", "is-active"]
        assert call.kwargs["shell"] is False


def test_org_sync_reports_http_error_body_for_diagnostics() -> None:
    error = urllib.error.HTTPError(
        url="http://127.0.0.1:18092/api/v1/org/sync",
        code=500,
        msg="Internal Server Error",
        hdrs={},
        fp=None,
    )
    error.read = lambda limit=-1: b'{"detail":"database is locked"}'  # type: ignore[method-assign]

    with patch("src.orchestrator.cron_scheduler.urllib.request.urlopen", side_effect=error):
        result = _org_sync()

    assert result == 'HTTP 500: {"detail":"database is locked"}'


def test_subordinate_balance_does_not_shadow_imported_modules() -> None:
    local_names = query_subordinate_balance.__code__.co_varnames

    assert "json" not in local_names
    assert "urllib" not in local_names
