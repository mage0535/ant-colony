from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.platform.employee_bot_service import get_employee_bot_assignment
from src.platform.org_graph import OrgGraphService
from src.store.database import Database

_AUDIT_DB = Path("data/audit/capability_audit.sqlite3")


def list_admin_user_details(platform: str = "wecom", *, sync: bool = True) -> dict[str, Any]:
    normalized = _normalize_platform(platform)
    graph = OrgGraphService()
    if sync:
        graph.sync_if_stale(normalized)
    users = _list_org_users(normalized)
    departments = _list_departments(normalized)
    usage = _load_usage_by_user(normalized)
    details = []
    for user in users:
        user_id = user["user_id"]
        assignment = get_employee_bot_assignment(normalized, user_id) or {}
        memberships = _list_memberships(normalized, user_id)
        details.append(
            {
                **user,
                "departments": memberships,
                "department_path": _department_path(memberships, departments),
                "is_admin": any(item.get("is_admin") for item in memberships),
                "is_leader": any(item.get("is_leader") for item in memberships),
                "online_status": _infer_online_status(user_id, usage),
                "bot_status": assignment.get("status", "not_opened"),
                "bot_display_name": assignment.get("display_name", ""),
                "bot_notify_status": assignment.get("notify_status", ""),
                "usage": usage.get(user_id, _empty_usage()),
            }
        )
    return {
        "platform": normalized,
        "departments": list(departments.values()),
        "users": details,
        "generated_at": time.time(),
    }


def _list_org_users(platform: str) -> list[dict[str, Any]]:
    conn = Database.get().connect()
    rows = conn.execute(
        """
        SELECT platform, user_id, name, email, mobile, title, updated_at
        FROM org_users
        WHERE platform = ?
        ORDER BY name, user_id
        """,
        (platform,),
    ).fetchall()
    return [
        {
            "platform": row["platform"],
            "user_id": row["user_id"],
            "name": row["name"],
            "email": row["email"],
            "mobile": row["mobile"],
            "title": row["title"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def _list_departments(platform: str) -> dict[str, dict[str, Any]]:
    conn = Database.get().connect()
    rows = conn.execute(
        """
        SELECT dept_id, name, parent_dept_id, updated_at
        FROM org_departments
        WHERE platform = ?
        ORDER BY parent_dept_id, dept_id
        """,
        (platform,),
    ).fetchall()
    return {
        str(row["dept_id"]): {
            "dept_id": str(row["dept_id"]),
            "name": row["name"],
            "parent_dept_id": str(row["parent_dept_id"] or ""),
            "updated_at": row["updated_at"],
        }
        for row in rows
    }


def _list_memberships(platform: str, user_id: str) -> list[dict[str, Any]]:
    conn = Database.get().connect()
    rows = conn.execute(
        """
        SELECT m.dept_id, d.name, m.is_leader, m.is_admin, m.updated_at
        FROM org_memberships m
        LEFT JOIN org_departments d ON d.platform = m.platform AND d.dept_id = m.dept_id
        WHERE m.platform = ? AND m.user_id = ?
        ORDER BY m.dept_id
        """,
        (platform, user_id),
    ).fetchall()
    return [
        {
            "dept_id": str(row["dept_id"]),
            "dept_name": row["name"] or str(row["dept_id"]),
            "is_leader": bool(row["is_leader"]),
            "is_admin": bool(row["is_admin"]),
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def _department_path(memberships: list[dict[str, Any]], departments: dict[str, dict[str, Any]]) -> str:
    if not memberships:
        return ""
    names = []
    for membership in memberships:
        dept = departments.get(str(membership.get("dept_id"))) or {}
        names.append(str(dept.get("name") or membership.get("dept_name") or membership.get("dept_id")))
    return " / ".join(dict.fromkeys(names))


def _load_usage_by_user(platform: str) -> dict[str, dict[str, Any]]:
    usage: dict[str, dict[str, Any]] = {}
    if not _AUDIT_DB.exists():
        return usage
    conn = sqlite3.connect(_AUDIT_DB)
    conn.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc)
    windows = {
        "day": now - timedelta(days=1),
        "week": now - timedelta(days=7),
        "month": now - timedelta(days=30),
        "year": now - timedelta(days=365),
    }
    try:
        rows = conn.execute(
            """
            SELECT timestamp, user_id, platform, capability_id, success, details_json, metadata_json
            FROM capability_audit
            WHERE user_id != ''
            ORDER BY id DESC
            """
        ).fetchall()
    finally:
        conn.close()
    for row in rows:
        row_platform = str(row["platform"] or "")
        if platform and row_platform and platform not in row_platform:
            continue
        user_id = str(row["user_id"])
        item = usage.setdefault(user_id, _empty_usage())
        ts = _parse_ts(str(row["timestamp"] or ""))
        estimated = _estimate_tokens(row["details_json"], row["metadata_json"])
        item["total_calls"] += 1
        item["estimated_tokens"] += estimated
        if bool(row["success"]):
            item["success_calls"] += 1
        else:
            item["failed_calls"] += 1
        item["last_seen_at"] = max(item.get("last_seen_at", 0.0), ts.timestamp() if ts else 0.0)
        for key, since in windows.items():
            if ts and ts >= since:
                item[key]["calls"] += 1
                item[key]["estimated_tokens"] += estimated
    return usage


def _empty_usage() -> dict[str, Any]:
    return {
        "total_calls": 0,
        "success_calls": 0,
        "failed_calls": 0,
        "estimated_tokens": 0,
        "last_seen_at": 0.0,
        "day": {"calls": 0, "estimated_tokens": 0},
        "week": {"calls": 0, "estimated_tokens": 0},
        "month": {"calls": 0, "estimated_tokens": 0},
        "year": {"calls": 0, "estimated_tokens": 0},
    }


def _parse_ts(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _estimate_tokens(details_json: str, metadata_json: str) -> int:
    try:
        details = json.loads(details_json or "{}")
        metadata = json.loads(metadata_json or "{}")
    except json.JSONDecodeError:
        return 0
    raw = json.dumps({"details": details, "metadata": metadata}, ensure_ascii=False)
    return max(1, len(raw) // 4)


def _infer_online_status(user_id: str, usage_by_user: dict[str, dict[str, Any]]) -> str:
    last_seen = float(usage_by_user.get(user_id, {}).get("last_seen_at") or 0.0)
    if not last_seen:
        return "unknown"
    if time.time() - last_seen < 10 * 60:
        return "recently_active"
    return "offline_or_idle"


def _normalize_platform(platform: str) -> str:
    normalized = platform.strip().lower() or "wecom"
    if normalized not in {"wecom", "feishu", "dingtalk"}:
        return "wecom"
    return normalized
