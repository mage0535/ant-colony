from __future__ import annotations

import time
from typing import Any

from src.store.database import Database


def set_hr_specialist(
    *,
    platform: str = "wecom",
    user_id: str,
    enabled: bool = True,
    granted_by: str = "",
) -> dict[str, Any]:
    normalized = _normalize_platform(platform)
    normalized_user = str(user_id or "").strip()
    if not normalized_user:
        raise ValueError("缺少员工企业 IM 用户 ID")
    conn = _conn()
    now = time.time()
    if enabled:
        conn.execute(
            """
            INSERT INTO hr_specialists (platform, user_id, granted_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(platform, user_id) DO UPDATE SET
                granted_by = excluded.granted_by,
                updated_at = excluded.updated_at
            """,
            (normalized, normalized_user, granted_by, now, now),
        )
    else:
        conn.execute(
            "DELETE FROM hr_specialists WHERE platform = ? AND user_id = ?",
            (normalized, normalized_user),
        )
    conn.commit()
    return {
        "platform": normalized,
        "user_id": normalized_user,
        "enabled": bool(enabled),
        "granted_by": granted_by,
        "updated_at": now,
    }


def bulk_set_hr_specialists(
    *,
    platform: str = "wecom",
    user_ids: list[str],
    enabled: bool = True,
    granted_by: str = "",
) -> dict[str, Any]:
    updated = 0
    results = []
    for user_id in user_ids:
        normalized_user = str(user_id or "").strip()
        if not normalized_user:
            continue
        results.append(
            set_hr_specialist(
                platform=platform,
                user_id=normalized_user,
                enabled=enabled,
                granted_by=granted_by,
            )
        )
        updated += 1
    return {"platform": _normalize_platform(platform), "enabled": bool(enabled), "updated": updated, "results": results}


def is_hr_specialist(platform: str = "wecom", user_id: str = "") -> bool:
    normalized_user = str(user_id or "").strip()
    if not normalized_user:
        return False
    row = _conn().execute(
        "SELECT 1 FROM hr_specialists WHERE platform = ? AND user_id = ?",
        (_normalize_platform(platform), normalized_user),
    ).fetchone()
    return row is not None


def list_hr_specialists(platform: str = "wecom") -> list[dict[str, Any]]:
    normalized = _normalize_platform(platform)
    rows = _conn().execute(
        """
        SELECT h.platform, h.user_id, h.granted_by, h.created_at, h.updated_at,
               u.name, u.email, u.mobile, u.title
        FROM hr_specialists h
        LEFT JOIN org_users u ON u.platform = h.platform AND u.user_id = h.user_id
        WHERE h.platform = ?
        ORDER BY COALESCE(NULLIF(u.name, ''), h.user_id)
        """,
        (normalized,),
    ).fetchall()
    return [
        {
            "platform": row["platform"],
            "user_id": row["user_id"],
            "name": row["name"] or "",
            "email": row["email"] or "",
            "mobile": row["mobile"] or "",
            "title": row["title"] or "",
            "granted_by": row["granted_by"] or "",
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def _conn():
    conn = Database.get().connect()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS hr_specialists (
            platform TEXT NOT NULL,
            user_id TEXT NOT NULL,
            granted_by TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (platform, user_id)
        )
        """
    )
    conn.commit()
    return conn


def _normalize_platform(platform: str) -> str:
    normalized = str(platform or "wecom").strip().lower() or "wecom"
    if normalized in {"wecom", "wecom_bot", "wecom_bot_ws", "企业微信", "企微"}:
        return "wecom"
    if normalized in {"feishu", "lark", "飞书"}:
        return "feishu"
    if normalized in {"dingtalk", "钉钉"}:
        return "dingtalk"
    return normalized
