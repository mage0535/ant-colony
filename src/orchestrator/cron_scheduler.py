"""Cron Scheduler — background loop that executes due jobs."""
from __future__ import annotations

import json
import logging
import subprocess
import time
import urllib.error
import urllib.request
from threading import Thread

from src.orchestrator.cron_job import CronJobRegistry, cron_result_status, run_no_agent

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 30  # seconds between due-job checks


class CronScheduler:
    """Lightweight scheduler that polls the registry and executes due jobs."""

    def __init__(self, registry: CronJobRegistry) -> None:
        self._registry = registry
        self._running = False
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = Thread(target=self._loop, daemon=True, name="cron-scheduler")
        self._thread.start()
        logger.info("CronScheduler started (check interval=%ds)", CHECK_INTERVAL)

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("CronScheduler stopped")

    def _loop(self) -> None:
        while self._running:
            try:
                due = self._registry.due_jobs()
                for job in due:
                    logger.info("Executing cron job: %s (no_agent=%s)", job.name, job.no_agent)
                    if job.no_agent:
                        result = run_no_agent(job.command)
                    else:
                        result = "REJECTED: agent mode cron execution is not implemented"
                    status = cron_result_status(result)
                    self._registry.record_run(job.id, status)
                    logger.info("Cron job %s result: %s", job.name, result[:200])
            except Exception as e:
                logger.error("CronScheduler loop error: %s", e)
            time.sleep(CHECK_INTERVAL)


def run_scheduler() -> None:
    """Entry point for the standalone scheduler process."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    from src.orchestrator.cron_job import get_registry
    reg = get_registry()
    _register_defaults(reg)
    sched = CronScheduler(reg)
    sched.start()
    logger.info("Cron scheduler running. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        sched.stop()


def _register_defaults(reg: CronJobRegistry) -> None:
    """Register built-in cron jobs."""
    from src.orchestrator.cron_job import CronJob
    defaults = [
        CronJob(
            id="org-sync",
            name="组织架构同步",
            schedule="0 3 * * *",
            command="python:src.orchestrator.cron_scheduler._org_sync",
            no_agent=True,
            tags=["system", "org"],
        ),
        CronJob(
            id="health-check",
            name="系统健康检查",
            schedule="every 30 min",
            command="python:src.orchestrator.cron_scheduler._health_check",
            no_agent=True,
            tags=["system", "health"],
        ),
        CronJob(
            id="process-change-notifier",
            name="审批/流程状态变更通知",
            schedule="every 1 min",
            command="python:src.platform.process_change_notifier.run_process_change_notifier",
            no_agent=True,
            tags=["system", "workflow", "notification"],
        ),
        CronJob(
            id="leave-quota-realtime-sync",
            name="假期额度实时同步",
            schedule="every 1 min",
            command="python:src.platform.leave_quota_service.run_realtime_leave_sync",
            no_agent=True,
            tags=["system", "workflow", "leave"],
        ),
        CronJob(
            id="daily-personal-brief",
            name="员工每日工作简报",
            schedule="every 30 min",
            command="python:src.platform.daily_brief_service.run_daily_briefs",
            no_agent=True,
            enabled=False,
            tags=["system", "brief", "notification"],
        ),
        CronJob(
            id="mail-new-message-notifier",
            name="企业邮箱新邮件提醒",
            schedule="every 1 min",
            command="python:src.platform.mail_account_service.run_mail_new_message_notifier",
            no_agent=True,
            tags=["system", "mail", "notification"],
        ),
        CronJob(
            id="public-data-subscriptions",
            name="公共数据订阅检查",
            schedule="every 30 min",
            command="python:src.platform.public_data_service.run_public_data_subscriptions",
            no_agent=True,
            tags=["system", "public-data", "notification"],
        ),
        CronJob(
            id="ratemin-pending-notifier",
            name="业务系统待办通知补发",
            schedule="every 1 min",
            command="python:src.platform.ratemin_service.run_ratemin_pending_notifier",
            no_agent=True,
            tags=["system", "ratemin", "notification"],
        ),
        CronJob(
            id="ratemin-collector-health",
            name="业务系统采集器健康检查",
            schedule="every 1 min",
            command="python:src.platform.ratemin_collector_health.run_ratemin_collector_health_check",
            no_agent=True,
            tags=["system", "ratemin", "health"],
        ),
    ]
    for j in defaults:
        existing = reg.get(j.id)
        if not existing:
            reg.register(j)
        else:
            changed = False
            if existing.command != j.command:
                existing.command = j.command
                existing.no_agent = True
                changed = True
            if j.id == "mail-new-message-notifier" and existing.schedule != j.schedule:
                existing.schedule = j.schedule
                existing.last_status = "已迁移：邮箱新邮件监听刷新频率为 1 分钟"
                changed = True
            if j.id == "process-change-notifier" and existing.schedule != j.schedule:
                existing.schedule = j.schedule
                existing.last_status = "process notifications migrated to every 1 min"
                changed = True
            # Daily briefs are retained for manual/audited use but must not
            # proactively message employees unless a later product decision enables them.
            if j.id == "daily-personal-brief" and existing.enabled:
                existing.enabled = False
                existing.last_status = "已停用：默认不主动推送每日工作简报"
                changed = True
            if changed:
                reg.register(existing)


def _health_check() -> str:
    """Built-in health check."""
    results = {}
    for svc in ["ant-colony-gateway", "ant-colony-dashboard", "gbrain-bridge",
                "hindsight-bridge", "embed-service", "ant-colony-org-sync.timer"]:
        completed = subprocess.run(
            ["systemctl", "is-active", svc],
            shell=False,
            capture_output=True,
            timeout=15,
        )
        results[svc] = "active" if completed.returncode == 0 else "inactive"
    return json.dumps(results, ensure_ascii=False)


def _org_sync() -> str:
    """Trigger organization synchronization through the local backend."""
    request = urllib.request.Request(
        "http://127.0.0.1:18092/api/v1/org/sync",
        data=b"",
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read(500).decode("utf-8", errors="replace")
            return f"HTTP {response.status}: {body}"
    except urllib.error.HTTPError as exc:
        body = exc.read(1000).decode("utf-8", errors="replace")
        return f"HTTP {exc.code}: {body}"


if __name__ == "__main__":
    run_scheduler()
