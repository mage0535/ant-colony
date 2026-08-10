from __future__ import annotations

import logging
import sqlite3
import time
from typing import Any

from src.platform.admin_registry import get_admin_ids
from src.platform.api_wecom import _get
from src.store.database import Database

logger = logging.getLogger(__name__)

_SYNC_TTL_SECONDS = 300.0
_SQLITE_LOCK_RETRY_ATTEMPTS = 6


class OrgGraphService:
    def __init__(self, db_path: str = "") -> None:
        self._db = Database.get(db_path)
        self._conn = self._db.connect()
        try:
            self._conn.execute("PRAGMA busy_timeout=30000")
        except Exception:
            logger.debug("failed to set org graph sqlite busy_timeout", exc_info=True)

    def _write_with_retry(self, action: Any) -> None:
        delay = 0.05
        for attempt in range(_SQLITE_LOCK_RETRY_ATTEMPTS):
            try:
                action()
                self._conn.commit()
                return
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() or attempt == _SQLITE_LOCK_RETRY_ATTEMPTS - 1:
                    raise
                try:
                    self._conn.rollback()
                except Exception:
                    pass
                time.sleep(delay)
                delay = min(delay * 2, 1.0)

    def upsert_department(self, platform: str, dept_id: str, name: str, parent_dept_id: str = "") -> None:
        def action() -> None:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO org_departments (platform, dept_id, name, parent_dept_id, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (platform, str(dept_id), name, str(parent_dept_id or ""), time.time()),
            )

        self._write_with_retry(action)

    def upsert_user(self, platform: str, user_id: str, name: str, *, email: str = "", mobile: str = "", title: str = "") -> None:
        def action() -> None:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO org_users (platform, user_id, name, email, mobile, title, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (platform, user_id, name, email, mobile, title, time.time()),
            )

        self._write_with_retry(action)

    def replace_user_memberships(self, platform: str, user_id: str, memberships: list[tuple[str, bool, bool]]) -> None:
        def action() -> None:
            self._conn.execute("DELETE FROM org_memberships WHERE platform = ? AND user_id = ?", (platform, user_id))
            for dept_id, is_leader, is_admin in memberships:
                self._conn.execute(
                    """
                    INSERT INTO org_memberships (platform, user_id, dept_id, is_leader, is_admin, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (platform, user_id, str(dept_id), 1 if is_leader else 0, 1 if is_admin else 0, time.time()),
                )

        self._write_with_retry(action)

    def is_admin(self, platform: str, user_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM org_memberships WHERE platform = ? AND user_id = ? AND is_admin = 1 LIMIT 1",
            (platform, user_id),
        ).fetchone()
        return row is not None

    def get_admin_ids(self, platform: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT user_id FROM org_memberships WHERE platform = ? AND is_admin = 1 ORDER BY user_id",
            (platform,),
        ).fetchall()
        return [str(row[0]) for row in rows]

    def is_department_leader(self, platform: str, user_id: str, dept_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM org_memberships WHERE platform = ? AND user_id = ? AND dept_id = ? AND is_leader = 1 LIMIT 1",
            (platform, user_id, str(dept_id)),
        ).fetchone()
        return row is not None

    def get_user_departments(self, platform: str, user_id: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT dept_id FROM org_memberships WHERE platform = ? AND user_id = ? ORDER BY dept_id",
            (platform, user_id),
        ).fetchall()
        return [str(row[0]) for row in rows]

    def get_leader_departments(self, platform: str, user_id: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT dept_id FROM org_memberships WHERE platform = ? AND user_id = ? AND is_leader = 1 ORDER BY dept_id",
            (platform, user_id),
        ).fetchall()
        return [str(row[0]) for row in rows]

    def get_department_members(self, platform: str, dept_id: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT user_id FROM org_memberships WHERE platform = ? AND dept_id = ? ORDER BY user_id",
            (platform, str(dept_id)),
        ).fetchall()
        return [str(row[0]) for row in rows]

    def get_department_leader_ids(self, platform: str, dept_id: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT user_id FROM org_memberships WHERE platform = ? AND dept_id = ? AND is_leader = 1 ORDER BY user_id",
            (platform, str(dept_id)),
        ).fetchall()
        return [str(row[0]) for row in rows]

    def find_user_by_name(self, platform: str, name: str, dept_id: str = "") -> str | None:
        if dept_id:
            row = self._conn.execute(
                """
                SELECT u.user_id
                FROM org_users u
                JOIN org_memberships m ON m.platform = u.platform AND m.user_id = u.user_id
                WHERE u.platform = ? AND u.name = ? AND m.dept_id = ?
                ORDER BY u.user_id
                LIMIT 1
                """,
                (platform, name, str(dept_id)),
            ).fetchone()
            if row:
                return str(row[0])
        row = self._conn.execute(
            "SELECT user_id FROM org_users WHERE platform = ? AND name = ? ORDER BY user_id LIMIT 1",
            (platform, name),
        ).fetchone()
        return str(row[0]) if row else None

    def get_users_by_ids(self, platform: str, user_ids: list[str]) -> list[dict[str, Any]]:
        if not user_ids:
            return []
        placeholders = ",".join("?" for _ in user_ids)
        rows = self._conn.execute(
            f"SELECT user_id, name, email, mobile, title FROM org_users WHERE platform = ? AND user_id IN ({placeholders})",
            [platform, *user_ids],
        ).fetchall()
        return [
            {"user_id": row[0], "name": row[1], "email": row[2], "mobile": row[3], "title": row[4]}
            for row in rows
        ]

    def get_user_profile(self, platform: str, user_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT user_id, name, email, mobile, title FROM org_users WHERE platform = ? AND user_id = ?",
            (platform, user_id),
        ).fetchone()
        if not row:
            return None
        return {
            "user_id": row[0],
            "name": row[1],
            "email": row[2],
            "mobile": row[3],
            "title": row[4],
            "departments": self.get_user_departments(platform, user_id),
            "leader_departments": self.get_leader_departments(platform, user_id),
            "is_admin": self.is_admin(platform, user_id),
        }

    def sync_if_stale(self, platform: str = "wecom", max_age_seconds: float = _SYNC_TTL_SECONDS) -> bool:
        if platform != "wecom":
            return False
        row = self._conn.execute(
            """
            SELECT MAX(updated_at) FROM (
                SELECT updated_at FROM org_users WHERE platform = ?
                UNION ALL
                SELECT updated_at FROM org_departments WHERE platform = ?
                UNION ALL
                SELECT updated_at FROM org_memberships WHERE platform = ?
            )
            """,
            (platform, platform, platform),
        ).fetchone()
        last_updated = float(row[0] or 0) if row else 0.0
        if last_updated and time.time() - last_updated < max_age_seconds:
            return False
        try:
            self.sync_wecom_directory()
            return True
        except Exception:
            logger.debug("WeCom directory sync_if_stale failed", exc_info=True)
            return False

    def sync_wecom_directory(self) -> dict[str, int]:
        platform = "wecom"
        dept_resp = _get("department/list")
        departments = dept_resp.get("department", [])
        for dept in departments:
            self.upsert_department(platform, str(dept.get("id", "")), dept.get("name", ""), str(dept.get("parentid", "")))

        user_resp = _get("user/list", "department_id=1&fetch_child=1")
        users = user_resp.get("userlist", [])
        admin_ids = get_admin_ids("wecom")
        for user in users:
            user_id = user.get("userid", "")
            if not user_id:
                continue
            dept_ids = [str(d) for d in (user.get("department", []) or [])]
            leader_flags = user.get("is_leader_in_dept", []) or []
            self.upsert_user(
                platform,
                user_id,
                user.get("name", ""),
                email=user.get("email", ""),
                mobile=user.get("mobile", ""),
                title=user.get("alias", ""),
            )
            memberships: list[tuple[str, bool, bool]] = []
            for index, dept_id in enumerate(dept_ids):
                is_leader = bool(index < len(leader_flags) and leader_flags[index])
                memberships.append((dept_id, is_leader, user_id in admin_ids))
            if not memberships:
                memberships.append(("", False, user_id in admin_ids))
            self.replace_user_memberships(platform, user_id, memberships)
        return {"departments": len(departments), "users": len(users)}
