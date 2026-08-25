from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from typing import Any

from src.gateway import provider_outbound
from src.store.database import Database


DEFAULT_MAX_STALE_SECONDS = 180
DEFAULT_ALERT_MIN_INTERVAL_SECONDS = 600


def check_ratemin_collector_health(*, wake: bool = True) -> dict[str, Any]:
    """Check whether the RatMin Windows collector is still syncing current todos."""
    max_stale = _max_stale_seconds()
    now = time.time()
    latest = _latest_current_sync()
    age = None if latest <= 0 else max(0.0, now - latest)
    healthy = age is not None and age <= max_stale
    result: dict[str, Any] = {
        "healthy": healthy,
        "latest_sync_at": latest,
        "age_seconds": None if age is None else round(age, 1),
        "max_stale_seconds": max_stale,
        "wake_attempted": False,
        "wake_status": "not_needed" if healthy else "not_configured",
    }
    if not healthy and wake:
        result.update(_wake_collector())
    result.update(_handle_status_alert(result, now))
    return result


def get_ratemin_channel_status(*, platform: str = "wecom") -> dict[str, Any]:
    """Return an operator-facing diagnosis for the RatMin notification channel."""
    normalized_platform = (platform or "wecom").strip().lower() or "wecom"
    health = check_ratemin_collector_health(wake=False)
    data_status = _ratemin_data_status(normalized_platform)
    project_status = _project_channel_status(normalized_platform)
    problem_origin = _problem_origin(health, data_status, project_status)
    overall = _overall_channel_status(problem_origin, health, data_status, project_status)
    return {
        "platform": normalized_platform,
        "overall_status": overall,
        "problem_origin": problem_origin,
        "ratemin_server": {
            "status": "healthy" if health.get("healthy") else "unhealthy",
            "summary": _ratemin_summary(health, data_status),
            "latest_sync_at": health.get("latest_sync_at"),
            "age_seconds": health.get("age_seconds"),
            "max_stale_seconds": health.get("max_stale_seconds"),
            "source_databases": data_status.get("source_databases", []),
            "current_events": data_status.get("current_events", []),
        },
        "project_server": project_status,
        "auto_recovery_available": bool(os.environ.get("RATEMIN_COLLECTOR_WAKE_COMMAND", "").strip()),
        "manual_steps": _manual_recovery_steps(),
        "checked_at": time.time(),
    }


def recover_ratemin_channel(*, platform: str = "wecom") -> dict[str, Any]:
    """Try safe project-side and configured collector-side recovery actions."""
    normalized_platform = (platform or "wecom").strip().lower() or "wecom"
    health = check_ratemin_collector_health(wake=True)
    flush_result: dict[str, Any]
    try:
        from src.platform.ratemin_service import flush_pending_ratemin_notifications

        flush_result = flush_pending_ratemin_notifications(platform=normalized_platform, limit=200)
    except Exception as exc:
        flush_result = {"platform": normalized_platform, "checked": 0, "sent": 0, "failed": 1, "error": str(exc)[:500]}
    return {
        "platform": normalized_platform,
        "collector_recovery": health,
        "project_recovery": flush_result,
        "status_after_recovery": get_ratemin_channel_status(platform=normalized_platform),
    }


def run_ratemin_collector_health_check() -> str:
    """Cron entrypoint used by the project server."""
    return json.dumps(check_ratemin_collector_health(wake=True), ensure_ascii=False)


def _latest_current_sync() -> float:
    conn = Database.get().connect()
    try:
        row = conn.execute("SELECT max(updated_at) AS updated_at FROM ratemin_current_events").fetchone()
    except Exception:
        return 0.0
    if not row:
        return 0.0
    try:
        return float(row["updated_at"] or 0)
    except Exception:
        return 0.0


def _wake_collector() -> dict[str, Any]:
    command = os.environ.get("RATEMIN_COLLECTOR_WAKE_COMMAND", "").strip()
    if not command:
        return {"wake_attempted": False, "wake_status": "not_configured"}
    timeout = int(os.environ.get("RATEMIN_COLLECTOR_WAKE_TIMEOUT", "30") or "30")
    use_shell = os.environ.get("RATEMIN_COLLECTOR_WAKE_SHELL", "").strip().lower() in {"1", "true", "yes"}
    try:
        command_args: str | list[str] = command if use_shell else shlex.split(command)
        if not command_args:
            return {"wake_attempted": False, "wake_status": "not_configured"}
        completed = subprocess.run(
            command_args,
            shell=use_shell,
            capture_output=True,
            text=True,
            timeout=max(5, timeout),
        )
    except Exception as exc:
        return {"wake_attempted": True, "wake_status": "exception", "wake_error": str(exc)[:500]}
    output = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
    return {
        "wake_attempted": True,
        "wake_status": "ok" if completed.returncode == 0 else "failed",
        "wake_returncode": completed.returncode,
        "wake_output": output[:500],
    }


def _handle_status_alert(result: dict[str, Any], now: float) -> dict[str, Any]:
    previous_status = _get_state("last_health_status")
    current_status = "healthy" if result.get("healthy") else "unhealthy"
    _set_state("last_health_status", current_status, now)

    targets = _alert_user_ids()
    if not targets:
        return {"alert_attempted": False, "alert_status": "not_configured"}

    platform = os.environ.get("RATEMIN_COLLECTOR_ALERT_PLATFORM", "wecom").strip() or "wecom"
    if current_status == "unhealthy":
        last_alert_at = _get_state_float("last_unhealthy_alert_at")
        min_interval = _alert_min_interval_seconds()
        if last_alert_at and now - last_alert_at < min_interval:
            return {
                "alert_attempted": False,
                "alert_status": "throttled",
                "alert_targets": len(targets),
            }
        sent = _send_alerts(platform, targets, _compose_unhealthy_alert(result))
        _set_state("last_unhealthy_alert_at", str(now), now)
        return {
            "alert_attempted": True,
            "alert_status": "sent" if sent else "send_failed",
            "alert_targets": len(targets),
            "alert_sent": sent,
        }

    if previous_status == "unhealthy":
        sent = _send_alerts(platform, targets, _compose_recovery_alert(result))
        _set_state("last_recovery_alert_at", str(now), now)
        return {
            "alert_attempted": True,
            "alert_status": "recovery_sent" if sent else "recovery_send_failed",
            "alert_targets": len(targets),
            "alert_sent": sent,
        }
    return {"alert_attempted": False, "alert_status": "not_needed"}


def _compose_unhealthy_alert(result: dict[str, Any]) -> str:
    age = result.get("age_seconds")
    age_text = "从未收到当前待办快照" if age is None else f"当前待办快照已 {age} 秒未更新"
    wake_status = result.get("wake_status") or "unknown"
    return (
        "【业务系统采集器异常】\n"
        f"{age_text}，已超过阈值 {result.get('max_stale_seconds')} 秒。\n"
        f"服务器侧唤醒状态：{wake_status}。\n"
        "请检查 Windows 业务系统采集器和本地 Watchdog 是否正常运行；恢复后系统会再次通知。"
    )


def _compose_recovery_alert(result: dict[str, Any]) -> str:
    return (
        "【业务系统采集器恢复】\n"
        f"当前待办快照已恢复同步，最近同步距现在 {result.get('age_seconds')} 秒。\n"
        "后续新增业务系统待办会继续自动推送到企业 AI 助手。"
    )


def _send_alerts(platform: str, targets: list[str], text: str) -> int:
    sent = 0
    for target in targets:
        try:
            if provider_outbound.send_platform_text(platform, target, text):
                sent += 1
        except Exception:
            continue
    return sent


def _ratemin_data_status(platform: str) -> dict[str, Any]:
    conn = Database.get().connect()
    try:
        rows = conn.execute(
            """
            SELECT source_db, count(*) AS c, max(updated_at) AS latest_sync_at
            FROM ratemin_current_events
            WHERE target_platform = ? OR target_platform = ''
            GROUP BY source_db
            ORDER BY source_db
            """,
            (platform,),
        ).fetchall()
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:500], "source_databases": [], "current_events": []}
    now = time.time()
    events = []
    for row in rows:
        latest = float(row["latest_sync_at"] or 0)
        events.append(
            {
                "source_db": row["source_db"],
                "count": int(row["c"] or 0),
                "latest_sync_at": latest,
                "age_seconds": round(max(0.0, now - latest), 1) if latest else None,
            }
        )
    return {
        "ok": True,
        "source_databases": [item["source_db"] for item in events],
        "current_events": events,
    }


def _project_channel_status(platform: str) -> dict[str, Any]:
    conn = Database.get().connect()
    status: dict[str, Any] = {
        "status": "healthy",
        "summary": "项目服务器可连接数据库，通知补发队列没有失败项。",
        "pending_status": [],
        "ready_count": 0,
        "failed_count": 0,
        "no_active_ai_assistant_count": 0,
        "unmatched_count": 0,
    }
    try:
        rows = conn.execute(
            """
            SELECT delivery_status, count(*) AS c
            FROM ratemin_pending_events
            WHERE target_platform = ? OR target_platform = ''
            GROUP BY delivery_status
            ORDER BY delivery_status
            """,
            (platform,),
        ).fetchall()
    except Exception as exc:
        return {
            **status,
            "status": "unhealthy",
            "summary": f"项目服务器数据库或业务系统通知表异常：{str(exc)[:200]}",
            "error": str(exc)[:500],
        }
    pending_status = [{"delivery_status": str(row["delivery_status"] or ""), "count": int(row["c"] or 0)} for row in rows]
    counts = {item["delivery_status"]: item["count"] for item in pending_status}
    failed_count = int(counts.get("send_failed", 0) or 0)
    ready_count = int(counts.get("ready", 0) or 0)
    status.update(
        {
            "pending_status": pending_status,
            "ready_count": ready_count,
            "failed_count": failed_count,
            "no_active_ai_assistant_count": int(counts.get("no_active_ai_assistant", 0) or 0),
            "unmatched_count": int(counts.get("unmatched", 0) or 0),
        }
    )
    if failed_count:
        status["status"] = "unhealthy"
        status["summary"] = f"项目服务器存在 {failed_count} 条发送失败通知，需要先尝试补发。"
    elif ready_count:
        status["status"] = "degraded"
        status["summary"] = f"项目服务器存在 {ready_count} 条待补发通知，cron 通常会自动处理。"
    return status


def _problem_origin(health: dict[str, Any], data_status: dict[str, Any], project_status: dict[str, Any]) -> str:
    ratemin_bad = (not health.get("healthy")) or (not data_status.get("ok", True))
    project_bad = project_status.get("status") in {"unhealthy", "degraded"}
    if ratemin_bad and project_bad:
        return "mixed"
    if ratemin_bad:
        return "ratemin_server"
    if project_bad:
        return "project_server"
    return "none"


def _overall_channel_status(
    problem_origin: str,
    health: dict[str, Any],
    data_status: dict[str, Any],
    project_status: dict[str, Any],
) -> str:
    if problem_origin == "none":
        return "healthy"
    if (not health.get("healthy")) or (not data_status.get("ok", True)) or project_status.get("status") == "unhealthy":
        return "unhealthy"
    return "degraded"


def _ratemin_summary(health: dict[str, Any], data_status: dict[str, Any]) -> str:
    if not data_status.get("ok", True):
        return f"项目服务器无法读取业务系统当前快照：{data_status.get('error', '')}"
    if health.get("healthy"):
        age = health.get("age_seconds")
        return f"业务系统 Windows 采集器正在同步，最近同步距现在 {age} 秒。"
    age = health.get("age_seconds")
    if age is None:
        return "项目服务器尚未收到业务系统当前待办快照，优先检查业务系统 Windows 采集器。"
    return f"业务系统当前待办快照已 {age} 秒未更新，优先检查业务系统 Windows 服务器采集器。"


def _manual_recovery_steps() -> dict[str, list[str]]:
    return {
        "project_server": [
            "在项目服务器检查服务状态：systemctl is-active ant-colony-dashboard ant-colony-cron ant-colony-wecom-bot",
            "如 dashboard 或 cron 异常，执行：sudo systemctl restart ant-colony-dashboard ant-colony-cron",
            "如企微推送异常，执行：sudo systemctl restart ant-colony-wecom-bot ant-colony-gateway",
            "重启后等待 1-2 分钟，再刷新本页面确认 ready/send_failed 是否归零。",
        ],
        "ratemin_server": [
            "登录业务系统 Windows 服务器。",
            "打开任务计划程序，找到 AntColony-Ratemin-Collector 和 AntColony-Ratemin-Collector-Watchdog。",
            "确认 Watchdog 为启用状态；如果 Collector 没有运行，右键 AntColony-Ratemin-Collector 后选择“运行”。",
            "如果仍不恢复，进入 C:\\SSSoft\\ant-colony-ratemin，双击或用 PowerShell 运行 ratemin_collector.ps1。",
            "确认该服务器能访问项目服务器的 /api/v1/site/ratemin/current/ingest 和 /users/ingest 接口。",
        ],
    }


def _alert_user_ids() -> list[str]:
    raw = os.environ.get("RATEMIN_COLLECTOR_ALERT_USER_IDS", "").strip()
    if not raw:
        return []
    return [part.strip() for part in raw.replace(";", ",").split(",") if part.strip()]


def _alert_min_interval_seconds() -> int:
    raw = os.environ.get("RATEMIN_COLLECTOR_ALERT_MIN_INTERVAL_SECONDS", "").strip()
    if not raw:
        return DEFAULT_ALERT_MIN_INTERVAL_SECONDS
    try:
        parsed = int(raw)
    except ValueError:
        return DEFAULT_ALERT_MIN_INTERVAL_SECONDS
    return max(60, parsed)


def _get_state(key: str) -> str:
    conn = _state_conn()
    row = conn.execute("SELECT value FROM ratemin_collector_health_state WHERE state_key = ?", (key,)).fetchone()
    return str(row["value"]) if row else ""


def _get_state_float(key: str) -> float:
    try:
        return float(_get_state(key) or 0)
    except ValueError:
        return 0.0


def _set_state(key: str, value: str, now: float) -> None:
    conn = _state_conn()
    conn.execute(
        """
        INSERT INTO ratemin_collector_health_state(state_key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(state_key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """,
        (key, value, now),
    )
    conn.commit()


def _state_conn():
    conn = Database.get().connect()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ratemin_collector_health_state (
            state_key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def _max_stale_seconds() -> int:
    raw = os.environ.get("RATEMIN_COLLECTOR_MAX_STALE_SECONDS", "").strip()
    if not raw:
        return DEFAULT_MAX_STALE_SECONDS
    try:
        parsed = int(raw)
    except ValueError:
        return DEFAULT_MAX_STALE_SECONDS
    return max(30, parsed)
