"""Cron Scheduler — background loop that executes due jobs."""
from __future__ import annotations

import logging
import time
from threading import Thread

from src.orchestrator.cron_job import CronJobRegistry, run_no_agent

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
                        result = "(agent mode not yet implemented)"
                    status = "OK" if not result.startswith(("FAILED", "EXCEPTION")) else result[:100]
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
            command="curl -s -o /dev/null -w '%{http_code}' -X POST http://localhost:18092/api/v1/org/sync",
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
    ]
    for j in defaults:
        if not reg.get(j.id):
            reg.register(j)


if __name__ == "__main__":
    run_scheduler()


def _health_check() -> str:
    """Built-in health check."""
    import os, json
    results = {}
    for svc in ["ant-colony-gateway", "ant-colony-dashboard", "gbrain-bridge",
                "hindsight-bridge", "embed-service", "ant-colony-org-sync.timer"]:
        r = os.system(f"systemctl is-active {svc} >/dev/null 2>&1")
        results[svc] = "active" if r == 0 else "inactive"
    return json.dumps(results, ensure_ascii=False)
