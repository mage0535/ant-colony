from __future__ import annotations

import json
import time
from typing import Any

from src.store.database import Database


def _conn():
    conn = Database.get().connect()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS employee_bot_assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            user_id TEXT NOT NULL,
            display_name TEXT NOT NULL DEFAULT '',
            scope TEXT NOT NULL DEFAULT 'personal',
            permissions_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'active',
            activated_by TEXT NOT NULL DEFAULT '',
            notify_status TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            UNIQUE(platform, user_id)
        )
        """
    )
    conn.commit()
    return conn


def activate_employee_bot(
    *,
    platform: str,
    user_id: str,
    display_name: str = "",
    scope: str = "personal",
    permissions: list[str] | None = None,
    activated_by: str = "",
    notify: bool = True,
) -> dict[str, Any]:
    normalized_platform = _normalize_platform(platform)
    normalized_user_id = user_id.strip()
    if not normalized_user_id:
        raise ValueError("缺少员工企业 IM 用户 ID")
    access = _derive_employee_access(normalized_platform, normalized_user_id)
    permissions = access["permissions"]
    scope = access["default_scope"]
    now = time.time()
    notify_status = "not_requested"
    if notify:
        notify_status = _notify_employee(normalized_platform, normalized_user_id, display_name)
    conn = _conn()
    conn.execute(
        """
        INSERT INTO employee_bot_assignments
            (platform, user_id, display_name, scope, permissions_json, status, activated_by, notify_status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
        ON CONFLICT(platform, user_id) DO UPDATE SET
            display_name = excluded.display_name,
            scope = excluded.scope,
            permissions_json = excluded.permissions_json,
            status = 'active',
            activated_by = excluded.activated_by,
            notify_status = excluded.notify_status,
            updated_at = excluded.updated_at
        """,
        (
            normalized_platform,
            normalized_user_id,
            display_name.strip() or _default_bot_name(normalized_platform),
            scope.strip() or "personal",
            json.dumps(permissions, ensure_ascii=False),
            activated_by,
            notify_status,
            now,
            now,
        ),
    )
    conn.commit()
    return get_employee_bot_assignment(normalized_platform, normalized_user_id) or {}


def deactivate_employee_bot(*, platform: str, user_id: str, updated_by: str = "") -> dict[str, Any]:
    return set_employee_bot_status(platform=platform, user_id=user_id, status="disabled", updated_by=updated_by)


def update_employee_bot_name(*, platform: str, user_id: str, display_name: str) -> dict[str, Any]:
    normalized_platform = _normalize_platform(platform)
    normalized_user_id = user_id.strip()
    conn = _conn()
    conn.execute(
        """
        UPDATE employee_bot_assignments
        SET display_name = ?, updated_at = ?
        WHERE platform = ? AND user_id = ?
        """,
        (display_name.strip() or _default_bot_name(normalized_platform), time.time(), normalized_platform, normalized_user_id),
    )
    conn.commit()
    return get_employee_bot_assignment(normalized_platform, normalized_user_id) or {}


def pause_employee_bot(*, platform: str, user_id: str, updated_by: str = "") -> dict[str, Any]:
    return set_employee_bot_status(platform=platform, user_id=user_id, status="paused", updated_by=updated_by)


def set_employee_bot_status(*, platform: str, user_id: str, status: str, updated_by: str = "") -> dict[str, Any]:
    normalized_platform = _normalize_platform(platform)
    normalized_user_id = user_id.strip()
    normalized_status = status.strip().lower()
    if normalized_status not in {"active", "disabled", "paused"}:
        raise ValueError(f"不支持的员工 AI 助手状态：{status}")
    conn = _conn()
    conn.execute(
        """
        UPDATE employee_bot_assignments
        SET status = ?, activated_by = ?, updated_at = ?
        WHERE platform = ? AND user_id = ?
        """,
        (normalized_status, updated_by, time.time(), normalized_platform, normalized_user_id),
    )
    conn.commit()
    return get_employee_bot_assignment(normalized_platform, normalized_user_id) or {
        "platform": normalized_platform,
        "user_id": normalized_user_id,
        "status": "not_found",
    }


def list_employee_bot_assignments(platform: str = "", limit: int = 200) -> list[dict[str, Any]]:
    conn = _conn()
    if platform:
        rows = conn.execute(
            """
            SELECT platform, user_id, display_name, scope, permissions_json, status, activated_by, notify_status, created_at, updated_at
            FROM employee_bot_assignments
            WHERE platform = ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (_normalize_platform(platform), int(limit)),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT platform, user_id, display_name, scope, permissions_json, status, activated_by, notify_status, created_at, updated_at
            FROM employee_bot_assignments
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def get_employee_bot_assignment(platform: str, user_id: str) -> dict[str, Any] | None:
    conn = _conn()
    row = conn.execute(
        """
        SELECT platform, user_id, display_name, scope, permissions_json, status, activated_by, notify_status, created_at, updated_at
        FROM employee_bot_assignments
        WHERE platform = ? AND user_id = ?
        """,
        (_normalize_platform(platform), user_id.strip()),
    ).fetchone()
    return _row_to_dict(row) if row else None


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "platform": row[0],
        "user_id": row[1],
        "display_name": row[2],
        "scope": row[3],
        "permissions": json.loads(row[4] or "[]"),
        "status": row[5],
        "activated_by": row[6],
        "notify_status": row[7],
        "created_at": row[8],
        "updated_at": row[9],
    }


def _notify_employee(platform: str, user_id: str, display_name: str) -> str:
    if platform != "wecom":
        return "simulated_pending_live_credentials"
    try:
        from src.gateway.wecom_outbound import send_text

        bot_name = display_name.strip() or _default_bot_name(platform)
        text = (
            f"你的企业 AI 助手已开通：{bot_name}\n"
            "你可以直接在企业微信中搜索并打开 AI 助手，发送“你好”开始使用。"
        )
        return "sent" if send_text(user_id, text) else "send_failed"
    except Exception as exc:
        return f"send_error:{exc}"


def _derive_employee_access(platform: str, user_id: str) -> dict[str, Any]:
    try:
        from src.knowledge.acl import default_write_scope, resolve_role, visible_scopes, writable_scopes

        role = resolve_role(user_id, platform=platform)
        default_scope = default_write_scope(role, user_id, platform=platform)
        readable = visible_scopes(role, user_id, platform=platform)
        writable = writable_scopes(role, user_id, platform=platform)
        permissions = ["chat.use", "files.process", "knowledge.read"]
        if writable:
            permissions.append("knowledge.write")
        if role.name == "admin":
            permissions.extend(["bot.manage", "knowledge.admin"])
        return {
            "role": role.name,
            "default_scope": f"{default_scope[0]}:{default_scope[1]}",
            "readable_scopes": [f"{owner_type}:{owner_id}" for owner_type, owner_id in readable],
            "writable_scopes": [f"{owner_type}:{owner_id}" for owner_type, owner_id in writable],
            "permissions": permissions,
        }
    except Exception:
        return {
            "role": "self",
            "default_scope": f"personal:{user_id}",
            "readable_scopes": [f"personal:{user_id}", "organization:*"],
            "writable_scopes": [f"personal:{user_id}"],
            "permissions": ["chat.use", "files.process", "knowledge.read", "knowledge.write"],
        }


def _normalize_platform(platform: str) -> str:
    normalized = platform.strip().lower() or "wecom"
    if normalized not in {"wecom", "feishu", "dingtalk"}:
        raise ValueError(f"不支持的平台：{platform}")
    return normalized


def _default_bot_name(platform: str) -> str:
    return {
        "wecom": "企业 AI 助手",
        "feishu": "飞书 AI 助手",
        "dingtalk": "钉钉 AI 助手",
    }.get(platform, "企业 AI 助手")
