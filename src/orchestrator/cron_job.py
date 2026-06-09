"""Cron Job model, registry, and persistence."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Any, Callable

logger = logging.getLogger(__name__)


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
                d["_last_run"] = d.pop("last_run", 0)
                d["_next_run"] = d.pop("next_run", 0)
                d["_run_count"] = d.pop("run_count", 0)
                d["_last_status"] = d.pop("last_status", "")
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
    now = base or time.time()
    expr = expr.strip().lower()

    if expr.startswith("every "):
        parts = expr.removeprefix("every ").split()
        if len(parts) >= 2:
            try:
                n = int(parts[0])
                unit = parts[1]
                multipliers = {"h": 3600, "hour": 3600, "hours": 3600,
                               "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
                               "d": 86400, "day": 86400, "days": 86400}
                seconds = n * multipliers.get(unit, 3600)
                return now + seconds
            except (ValueError, KeyError):
                pass

    if expr.startswith("0 ") or expr[0].isdigit():
        parts = expr.split()
        if len(parts) >= 5:
            try:
                minute = int(parts[0])
                hour = int(parts[1])
                day = int(parts[2]) if parts[2] != "*" else None
                month = int(parts[3]) if parts[3] != "*" else None
                weekday = int(parts[4]) if parts[4] != "*" else None
                dt = datetime.fromtimestamp(now)
                if hour < dt.hour or (hour == dt.hour and minute <= dt.minute):
                    dt = dt + timedelta(days=1)
                next_dt = dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if day:
                    next_dt = next_dt.replace(day=day)
                return next_dt.timestamp()
            except (ValueError, IndexError):
                pass

    return now + 3600  # default: retry in 1 hour


def run_no_agent(command: str) -> str:
    """Execute a no_agent job: import python module or run shell command."""
    try:
        if command.startswith("python:"):
            mod_path = command.removeprefix("python:")
            mod_parts = mod_path.rsplit(".", 1)
            if len(mod_parts) == 2:
                mod_name, func_name = mod_parts
                import importlib
                mod = importlib.import_module(mod_name)
                func = getattr(mod, func_name)
                result = func()
                return str(result)[:2000]
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            return f"FAILED (exit {result.returncode}): {result.stderr[:500]}"
        return result.stdout[:2000] or "OK (no output)"
    except Exception as e:
        return f"EXCEPTION: {e}"


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
