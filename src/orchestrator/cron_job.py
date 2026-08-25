"""Cron Job model, registry, and persistence."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

ALLOWED_NO_AGENT_CALLABLES = {
    "src.orchestrator.cron_scheduler._health_check",
    "src.orchestrator.cron_scheduler._org_sync",
    "src.platform.process_change_notifier.run_process_change_notifier",
    "src.platform.leave_quota_service.run_realtime_leave_sync",
    "src.platform.daily_brief_service.run_daily_briefs",
    "src.platform.mail_account_service.run_mail_new_message_notifier",
    "src.platform.public_data_service.run_public_data_subscriptions",
    "src.platform.ratemin_service.run_ratemin_pending_notifier",
    "src.platform.ratemin_collector_health.run_ratemin_collector_health_check",
}


@dataclass
class CronJob:
    id: str
    name: str
    schedule: str  # cron expression like "0 */30 * * * *" or "every 2h"
    command: str  # python module path or shell command
    no_agent: bool = True
    enabled: bool = True
    last_run: float = 0.0
    next_run: float = 0.0
    run_count: int = 0
    last_status: str = ""
    max_retries: int = 0
    retry_delay: int = 60
    tags: list[str] = field(default_factory=list)


class CronJobRegistry:
    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or os.environ.get("ANT_CRON_DB", "data/cron_jobs.json")
        self._jobs: dict[str, CronJob] = {}
        self._load()

    def register(self, job: CronJob) -> None:
        job.next_run = _parse_schedule(job.schedule)
        self._jobs[job.id] = job
        self._save()
        logger.info("Registered cron job: %s (schedule=%s, no_agent=%s)", job.name, job.schedule, job.no_agent)

    def unregister(self, job_id: str) -> bool:
        if job_id in self._jobs:
            del self._jobs[job_id]
            self._save()
            return True
        return False

    def get(self, job_id: str) -> CronJob | None:
        return self._jobs.get(job_id)

    def list(self) -> list[CronJob]:
        return list(self._jobs.values())

    def due_jobs(self) -> list[CronJob]:
        now = time.time()
        return [j for j in self._jobs.values() if j.enabled and j.next_run <= now]

    def record_run(self, job_id: str, status: str) -> None:
        job = self._jobs.get(job_id)
        if not job:
            return
        job.last_run = time.time()
        job.run_count += 1
        job.last_status = status
        job.next_run = _parse_schedule(job.schedule)
        self._save()

    def _load(self) -> None:
        if not self._db_path or not os.path.isfile(self._db_path):
            return
        try:
            with open(self._db_path, "r") as f:
                data = json.load(f)
            for d in data:
                for field_name, default in (
                    ("last_run", 0),
                    ("next_run", 0),
                    ("run_count", 0),
                    ("last_status", ""),
                ):
                    d.setdefault(field_name, d.pop(f"_{field_name}", default))
                j = CronJob(**{k: v for k, v in d.items() if k in CronJob.__dataclass_fields__})
                self._jobs[j.id] = j
        except Exception as e:
            logger.warning("Failed to load cron jobs: %s", e)

    def _save(self) -> None:
        if not self._db_path:
            return
        os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        data = [asdict(j) for j in self._jobs.values()]
        with open(self._db_path, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def _parse_schedule(expr: str, base: float | None = None) -> float:
    """Parse schedule expression and return next run timestamp."""
    now = time.time() if base is None else base
    expr = expr.strip().lower()

    interval = re.fullmatch(
        r"every\s+(\d+)\s*(m|min|mins|minute|minutes|h|hour|hours|d|day|days)",
        expr,
    )
    if interval:
        amount = int(interval.group(1))
        unit = interval.group(2)
        multiplier = {
            "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
            "h": 3600, "hour": 3600, "hours": 3600,
            "d": 86400, "day": 86400, "days": 86400,
        }[unit]
        return now + amount * multiplier

    parts = expr.split()
    if len(parts) == 5:
        try:
            minute = _parse_cron_field(parts[0], 0, 59)
            hour = _parse_cron_field(parts[1], 0, 23)
            day = _parse_cron_field(parts[2], 1, 31)
            month = _parse_cron_field(parts[3], 1, 12)
            weekday = _parse_cron_field(parts[4], 0, 7)
        except ValueError:
            pass
        else:
            candidate = datetime.fromtimestamp(now).replace(second=0, microsecond=0) + timedelta(minutes=1)
            for _ in range(366 * 24 * 60):
                cron_weekday = (candidate.weekday() + 1) % 7
                normalized_weekday = 0 if weekday == 7 else weekday
                day_matches = day is None or candidate.day == day
                weekday_matches = normalized_weekday is None or cron_weekday == normalized_weekday
                if day is not None and normalized_weekday is not None:
                    date_matches = day_matches or weekday_matches
                else:
                    date_matches = day_matches and weekday_matches
                if (
                    (minute is None or candidate.minute == minute)
                    and (hour is None or candidate.hour == hour)
                    and (month is None or candidate.month == month)
                    and date_matches
                ):
                    return candidate.timestamp()
                candidate += timedelta(minutes=1)

    return now + 3600  # default: retry in 1 hour


def _parse_cron_field(value: str, minimum: int, maximum: int) -> int | None:
    if value == "*":
        return None
    parsed = int(value)
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"cron field out of range: {value}")
    return parsed


def run_no_agent(command: str) -> str:
    """Execute an explicitly allowed internal no-agent callable."""
    if not command.startswith("python:"):
        return "REJECTED: command is not an allowed internal cron callable"
    mod_path = command.removeprefix("python:")
    if mod_path not in ALLOWED_NO_AGENT_CALLABLES:
        return "REJECTED: command is not an allowed internal cron callable"
    try:
        mod_name, func_name = mod_path.rsplit(".", 1)
        import importlib

        mod = importlib.import_module(mod_name)
        func = getattr(mod, func_name)
        return str(func())[:2000]
    except Exception as e:
        return f"EXCEPTION: {e}"


def cron_result_status(result: str) -> str:
    """Convert a cron execution result into the persisted status label."""
    text = str(result or "").strip()
    if text.startswith(("FAILED", "EXCEPTION", "REJECTED")):
        return text[:100]
    if "not yet implemented" in text.lower() or text.startswith("(agent mode"):
        return "REJECTED: agent mode cron execution is not implemented"
    return "OK"


REGISTRY: CronJobRegistry | None = None


def get_registry() -> CronJobRegistry:
    global REGISTRY
    if REGISTRY is None:
        REGISTRY = CronJobRegistry()
    return REGISTRY


def list_jobs() -> str:
    """Tool handler: list all registered cron jobs."""
    reg = get_registry()
    jobs = reg.list()
    if not jobs:
        return "暂无定时任务"
    lines = [f"定时任务列表 ({len(jobs)} 个):"]
    for j in jobs:
        status = "🟢" if j.enabled else "⚪"
        last = datetime.fromtimestamp(j.last_run).strftime("%m-%d %H:%M") if j.last_run else "从未"
        lines.append(f"  {status} {j.name} [{j.schedule}] 上次: {last} 状态: {j.last_status or '-'}")
    return "\n".join(lines)
