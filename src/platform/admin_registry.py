"""Admin registry — cross-platform admin user storage and management.

Since WeCom does not expose an API to query platform administrators,
this module provides a database-backed admin list that can be managed
via chat commands (add/remove/list admins).

For Feishu and DingTalk, the platform API is used as primary source,
with this DB list as an override/extension.

The registry stores admin user IDs indexed by platform:
  wecom: WeCom userid (e.g. "XieYu")
  feishu: Feishu open_id
  dingtalk: DingTalk userid
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


def _ensure_table():
    from src.store.database import Database
    conn = Database.get().connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS platform_admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            added_by TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL DEFAULT (cast(strftime('%s','now') as real)),
            UNIQUE(platform, user_id)
        )
    """)
    conn.commit()


def get_admin_ids(platform: str) -> set[str]:
    """Return all stored admin user IDs for a platform."""
    _ensure_table()
    from src.store.database import Database
    conn = Database.get().connect()
    rows = conn.execute(
        "SELECT user_id FROM platform_admins WHERE platform = ?", (platform,)
    ).fetchall()
    return {row[0] for row in rows}


def add_admin(platform: str, user_id: str, name: str = "", added_by: str = "") -> bool:
    """Add an admin user."""
    _ensure_table()
    from src.store.database import Database
    conn = Database.get().connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO platform_admins (platform, user_id, name, added_by) VALUES (?, ?, ?, ?)",
            (platform, user_id, name, added_by),
        )
        conn.commit()
        logger.info("Admin added: %s/%s (%s) by %s", platform, user_id, name, added_by)
        return True
    except Exception as e:
        logger.warning("Failed to add admin: %s", e)
        return False


def remove_admin(platform: str, user_id: str) -> bool:
    """Remove an admin user."""
    _ensure_table()
    from src.store.database import Database
    conn = Database.get().connect()
    conn.execute(
        "DELETE FROM platform_admins WHERE platform = ? AND user_id = ?",
        (platform, user_id),
    )
    deleted = conn.total_changes > 0
    conn.commit()
    if deleted:
        logger.info("Admin removed: %s/%s", platform, user_id)
    return deleted


def list_admins(platform: str) -> list[dict[str, Any]]:
    """List all stored admins for a platform."""
    _ensure_table()
    from src.store.database import Database
    conn = Database.get().connect()
    rows = conn.execute(
        "SELECT user_id, name, created_at FROM platform_admins WHERE platform = ? ORDER BY created_at",
        (platform,),
    ).fetchall()
    return [{"user_id": r[0], "name": r[1], "created_at": r[2]} for r in rows]
