from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from typing import Any

from src.gateway import provider_outbound
from src.store.database import Database


DEFAULT_PLATFORM = "wecom"
DEFAULT_SOURCE_DBS = ("business_a", "business_b")
_RATEMIN_WRITE_LOCK = threading.RLock()


def configured_source_dbs() -> tuple[str, ...]:
    raw = os.environ.get("RATEMIN_SOURCE_DBS", "")
    items = tuple(item.strip().lower() for item in raw.split(",") if item.strip())
    return items or DEFAULT_SOURCE_DBS


def ingest_ratemin_events(events: list[dict[str, Any]], *, platform: str = DEFAULT_PLATFORM) -> dict[str, Any]:
    """Ingest pending RatMin workflow events and push first-time notifications."""
    normalized_platform = _normalize_platform(platform)
    conn = _conn()
    result = {"received": len(events), "inserted": 0, "updated": 0, "notified": 0, "unmatched": 0, "skipped": 0, "errors": []}
    with _RATEMIN_WRITE_LOCK:
        for raw in events:
            try:
                event = _normalize_event(raw, normalized_platform)
                _upsert_user_snapshot(conn, event)
                binding = _resolve_binding(conn, event, normalized_platform)
                event["target_platform"] = normalized_platform
                event["target_user_id"] = binding.get("im_user_id", "") if binding else ""
                event["delivery_status"] = _initial_delivery_status(binding, normalized_platform)
                existing = _event_row(conn, event["source_db"], event["event_id"], event["recipient_oper_id"])
                if existing:
                    _update_event(conn, event, existing_status=str(existing["delivery_status"] or ""))
                    result["updated"] += 1
                    continue
                _insert_event(conn, event)
                result["inserted"] += 1
                if event["delivery_status"] == "ready":
                    ok = _send_event_notification(event)
                    _mark_event_delivery(
                        conn,
                        event,
                        "sent" if ok else "send_failed",
                        "" if ok else "provider_outbound returned false",
                    )
                    result["notified"] += 1 if ok else 0
                elif event["delivery_status"] == "unmatched":
                    result["unmatched"] += 1
                else:
                    result["skipped"] += 1
            except Exception as exc:
                result["errors"].append(str(exc))
    result["errors"] = result["errors"][:20]
    return result


def sync_ratemin_current_events(
    events: list[dict[str, Any]],
    *,
    platform: str = DEFAULT_PLATFORM,
    source_databases: list[str] | None = None,
) -> dict[str, Any]:
    """Refresh the read-only current RatMin todo snapshot used by user queries."""
    normalized_platform = _normalize_platform(platform)
    conn = _conn()
    normalized_events: list[dict[str, Any]] = []
    source_dbs = {_normalize_source_db(db) for db in (source_databases or []) if str(db or "").strip()}
    result = {"received": len(events), "active": 0, "source_databases": sorted(source_dbs), "errors": []}
    now = time.time()
    for raw in events:
        try:
            event = _normalize_event(raw, normalized_platform)
            source_dbs.add(event["source_db"])
            normalized_events.append(event)
        except Exception as exc:
            result["errors"].append(str(exc))
    _run_sqlite_write_with_retry(lambda: _sync_current_events_once(
        conn,
        source_dbs=source_dbs,
        normalized_events=normalized_events,
        normalized_platform=normalized_platform,
        now=now,
        result=result,
    ))
    result["source_databases"] = sorted(source_dbs)
    result["errors"] = result["errors"][:20]
    return result


def _sync_current_events_once(
    conn,
    *,
    source_dbs: set[str],
    normalized_events: list[dict[str, Any]],
    normalized_platform: str,
    now: float,
    result: dict[str, Any],
) -> None:
    result["active"] = 0
    with _RATEMIN_WRITE_LOCK:
        for db in source_dbs:
            conn.execute(
                """
                UPDATE ratemin_current_events
                SET current_status = 'stale', updated_at = ?
                WHERE target_platform = ? AND source_db = ?
                """,
                (now, normalized_platform, db),
            )
        for event in normalized_events:
            conn.execute(
                """
                INSERT INTO ratemin_current_events
                    (source_db, event_id, recipient_oper_id, target_platform, current_status, updated_at)
                VALUES (?, ?, ?, ?, 'active', ?)
                ON CONFLICT(source_db, event_id, recipient_oper_id, target_platform) DO UPDATE SET
                    current_status = 'active',
                    updated_at = excluded.updated_at
                """,
                (event["source_db"], event["event_id"], event["recipient_oper_id"], normalized_platform, now),
            )
            result["active"] += 1
        conn.commit()


def _run_sqlite_write_with_retry(action, *, attempts: int = 6) -> None:
    conn = _conn()
    for attempt in range(attempts):
        try:
            action()
            return
        except Exception as exc:
            if "database is locked" not in str(exc).lower() or attempt >= attempts - 1:
                raise
            try:
                conn.rollback()
            except Exception:
                pass
            time.sleep(0.15 * (attempt + 1))


def ingest_ratemin_user_snapshots(
    users: list[dict[str, Any]],
    *,
    platform: str = DEFAULT_PLATFORM,
    auto_bind: bool = True,
) -> dict[str, Any]:
    normalized_platform = _normalize_platform(platform)
    conn = _conn()
    result = {"received": len(users), "snapshots": 0, "auto_bound": 0, "ambiguous": 0, "unmatched": 0, "errors": []}
    with _RATEMIN_WRITE_LOCK:
        for raw in users:
            try:
                user = _normalize_snapshot_user(raw)
                _upsert_snapshot_user(conn, user)
                result["snapshots"] += 1
                if auto_bind:
                    state = _auto_bind_snapshot_user(conn, user, normalized_platform)
                    if state == "bound":
                        result["auto_bound"] += 1
                    elif state == "ambiguous":
                        result["ambiguous"] += 1
                    elif state == "unmatched":
                        result["unmatched"] += 1
            except Exception as exc:
                result["errors"].append(str(exc))
    result["errors"] = result["errors"][:20]
    return result


def list_ratemin_status(platform: str = DEFAULT_PLATFORM) -> dict[str, Any]:
    conn = _conn()
    normalized_platform = _normalize_platform(platform)
    rows = conn.execute(
        """
        SELECT source_db, delivery_status, count(*) AS c
        FROM ratemin_pending_events
        WHERE target_platform = ? OR target_platform = ''
        GROUP BY source_db, delivery_status
        ORDER BY source_db, delivery_status
        """,
        (normalized_platform,),
    ).fetchall()
    bindings = conn.execute(
        """
        SELECT source_db, status, match_method, count(*) AS c
        FROM ratemin_user_bindings
        WHERE platform = ?
        GROUP BY source_db, status, match_method
        ORDER BY source_db, status, match_method
        """,
        (normalized_platform,),
    ).fetchall()
    users = conn.execute("SELECT source_db, count(*) AS c FROM ratemin_user_snapshot GROUP BY source_db").fetchall()
    return {
        "platform": normalized_platform,
        "events": [_row_dict(r) for r in rows],
        "bindings": [_row_dict(r) for r in bindings],
        "user_snapshots": [_row_dict(r) for r in users],
        "source_dbs": list(configured_source_dbs()),
    }


def list_ratemin_bindings(platform: str = DEFAULT_PLATFORM, *, status: str = "", limit: int = 200) -> list[dict[str, Any]]:
    conn = _conn()
    normalized_platform = _normalize_platform(platform)
    if status:
        rows = conn.execute(
            """
            SELECT *
            FROM ratemin_user_bindings
            WHERE platform = ? AND status = ?
            ORDER BY source_db, rate_display_name, rate_login_name
            LIMIT ?
            """,
            (normalized_platform, status, int(limit)),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT *
            FROM ratemin_user_bindings
            WHERE platform = ?
            ORDER BY source_db, status, rate_display_name, rate_login_name
            LIMIT ?
            """,
            (normalized_platform, int(limit)),
        ).fetchall()
    return [_row_dict(row) for row in rows]


def list_ratemin_directory(
    platform: str = DEFAULT_PLATFORM,
    *,
    source_db: str = "",
    query: str = "",
    sort: str = "source_db",
    direction: str = "asc",
    limit: int = 500,
) -> list[dict[str, Any]]:
    conn = _conn()
    normalized_platform = _normalize_platform(platform)
    sort_columns = {
        "source_db": "s.source_db",
        "rate_oper_id": "s.rate_oper_id",
        "rate_login_name": "s.rate_login_name",
        "rate_display_name": "s.rate_display_name",
        "normalized_display_name": "s.normalized_display_name",
        "directory_status": "directory_status",
        "im_display_name": "im_display_name",
        "im_user_id": "im_user_id",
        "match_method": "match_method",
        "snapshot_updated_at": "s.updated_at",
    }
    order_col = sort_columns.get(str(sort or "").strip(), sort_columns["source_db"])
    order_dir = "DESC" if str(direction or "").lower() == "desc" else "ASC"
    params: list[Any] = [normalized_platform]
    where = ["1=1"]
    if source_db:
        where.append("s.source_db = ?")
        params.append(_normalize_source_db(source_db))
    if query.strip():
        like = f"%{query.strip()}%"
        where.append("(s.rate_display_name LIKE ? OR s.rate_login_name LIKE ? OR s.rate_oper_id LIKE ? OR ifnull(b.im_display_name,'') LIKE ? OR ifnull(b.im_user_id,'') LIKE ?)")
        params.extend([like, like, like, like, like])
    rows = conn.execute(
        f"""
        SELECT
            s.source_db,
            s.rate_oper_id,
            s.rate_login_name,
            s.rate_display_name,
            s.normalized_display_name,
            s.updated_at AS snapshot_updated_at,
            ifnull(b.im_user_id, '') AS im_user_id,
            ifnull(b.im_display_name, '') AS im_display_name,
            ifnull(b.match_method, '') AS match_method,
            ifnull(b.status, '') AS binding_status,
            case
                when b.im_user_id != '' then 'bound'
                else 'unbound'
            end AS directory_status
        FROM ratemin_user_snapshot s
        LEFT JOIN ratemin_user_bindings b
          ON b.source_db = s.source_db
         AND b.rate_oper_id = s.rate_oper_id
         AND b.platform = ?
        WHERE {' AND '.join(where)}
        ORDER BY {order_col} {order_dir}, s.source_db ASC, s.rate_display_name ASC, s.rate_login_name ASC, s.rate_oper_id ASC
        LIMIT ?
        """,
        (*params, int(limit)),
    ).fetchall()
    return [_row_dict(row) for row in rows]


def auto_bind_all_ratemin_users(
    *,
    platform: str = DEFAULT_PLATFORM,
    source_db: str = "",
    query: str = "",
    limit: int = 1000,
) -> dict[str, Any]:
    conn = _conn()
    normalized_platform = _normalize_platform(platform)
    directory = list_ratemin_directory(normalized_platform, source_db=source_db, query=query, limit=limit)
    result = {"platform": normalized_platform, "scanned": len(directory), "bound": 0, "skipped": 0, "ambiguous": 0, "unmatched": 0}
    for item in directory:
        if str(item.get("im_user_id") or ""):
            result["skipped"] += 1
            continue
        user = {
            "source_db": item["source_db"],
            "rate_oper_id": item["rate_oper_id"],
            "rate_login_name": item["rate_login_name"],
            "rate_display_name": item["rate_display_name"],
        }
        state = _auto_bind_snapshot_user(conn, user, normalized_platform)
        if state == "bound":
            result["bound"] += 1
        elif state == "ambiguous":
            result["ambiguous"] += 1
        elif state == "unmatched":
            result["unmatched"] += 1
        else:
            result["skipped"] += 1
    return result


def bind_ratemin_user(
    *,
    source_db: str,
    rate_login_name: str = "",
    rate_oper_id: str = "",
    rate_display_name: str = "",
    platform: str = DEFAULT_PLATFORM,
    im_user_id: str,
    im_display_name: str = "",
    created_by: str = "",
    match_method: str = "manual",
) -> dict[str, Any]:
    conn = _conn()
    normalized_platform = _normalize_platform(platform)
    source = _normalize_source_db(source_db)
    im_name = im_display_name or _lookup_im_display_name(conn, normalized_platform, im_user_id)
    now = time.time()
    conn.execute(
        """
        INSERT INTO ratemin_user_bindings
            (source_db, rate_oper_id, rate_login_name, rate_display_name, platform, im_user_id, im_display_name, match_method, status, created_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
        ON CONFLICT(source_db, rate_oper_id, platform) DO UPDATE SET
            rate_login_name = excluded.rate_login_name,
            rate_display_name = excluded.rate_display_name,
            im_user_id = excluded.im_user_id,
            im_display_name = excluded.im_display_name,
            match_method = excluded.match_method,
            status = 'active',
            created_by = excluded.created_by,
            updated_at = excluded.updated_at
        """,
        (
            source,
            str(rate_oper_id or rate_login_name or rate_display_name),
            rate_login_name,
            rate_display_name,
            normalized_platform,
            im_user_id,
            im_name,
            match_method,
            created_by,
            now,
            now,
        ),
    )
    conn.commit()
    return _row_dict(
        conn.execute(
            """
            SELECT *
            FROM ratemin_user_bindings
            WHERE source_db = ? AND rate_oper_id = ? AND platform = ?
            """,
            (source, str(rate_oper_id or rate_login_name or rate_display_name), normalized_platform),
        ).fetchone()
    )


def unbind_ratemin_user(*, source_db: str, rate_oper_id: str, platform: str = DEFAULT_PLATFORM) -> dict[str, Any]:
    conn = _conn()
    source = _normalize_source_db(source_db)
    normalized_platform = _normalize_platform(platform)
    conn.execute(
        """
        UPDATE ratemin_user_bindings
        SET status = 'disabled', updated_at = ?
        WHERE source_db = ? AND rate_oper_id = ? AND platform = ?
        """,
        (time.time(), source, str(rate_oper_id), normalized_platform),
    )
    conn.commit()
    return {"source_db": source, "rate_oper_id": str(rate_oper_id), "platform": normalized_platform, "status": "disabled"}


def query_my_ratemin_todos(
    *,
    platform: str,
    user_id: str,
    query: str = "",
    source_db: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    conn = _conn()
    normalized_platform = _normalize_platform(platform)
    source_filter = _normalize_source_db(source_db) if source_db else ""
    bindings = conn.execute(
        """
        SELECT source_db, rate_oper_id, rate_login_name, rate_display_name
        FROM ratemin_user_bindings
        WHERE platform = ? AND im_user_id = ? AND status = 'active'
        """,
        (normalized_platform, user_id),
    ).fetchall()
    if not bindings:
        return {"platform": normalized_platform, "user_id": user_id, "count": 0, "items": [], "message": "未找到你的业务系统账号绑定。"}
    allowed = {(str(r["source_db"]), str(r["rate_oper_id"])) for r in bindings}
    params: list[Any] = [normalized_platform, normalized_platform]
    where = ["e.target_platform = ?", "e.delivery_status IN ('sent','ready','send_failed','unmatched','no_active_ai_assistant')"]
    if source_filter:
        where.append("e.source_db = ?")
        params.append(source_filter)
    if query:
        like = f"%{query.strip()}%"
        where.append("(e.subject LIKE ? OR e.content LIKE ? OR e.flow_name LIKE ? OR e.initiator_name LIKE ? OR e.todo_time LIKE ?)")
        params.extend([like, like, like, like, like])
    rows = conn.execute(
        f"""
        SELECT e.*
        FROM ratemin_pending_events e
        JOIN ratemin_current_events c
          ON c.source_db = e.source_db
         AND c.event_id = e.event_id
         AND c.recipient_oper_id = e.recipient_oper_id
         AND c.target_platform = ?
         AND c.current_status = 'active'
        WHERE {' AND '.join(where)}
        ORDER BY e.todo_time DESC, e.created_at DESC
        LIMIT 500
        """,
        params,
    ).fetchall()
    items = [
        _row_dict(row)
        for row in rows
        if (str(row["source_db"]), str(row["recipient_oper_id"])) in allowed
    ][: int(limit)]
    return {
        "platform": normalized_platform,
        "user_id": user_id,
        "display_name": _lookup_im_display_name(conn, normalized_platform, user_id),
        "count": len(items),
        "items": items,
        "message": _format_todo_query_message(items, query=query, source_db=source_filter),
    }


def format_my_ratemin_todos(*, platform: str, user_id: str, query: str = "", source_db: str = "", limit: int = 20) -> str:
    result = query_my_ratemin_todos(platform=platform, user_id=user_id, query=query, source_db=source_db, limit=limit)
    return str(result["message"])


def query_ratemin_todos_for_target(
    *,
    platform: str,
    requester_user_id: str,
    target_user: str,
    query: str = "",
    source_db: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    normalized_platform = _normalize_platform(platform)
    target = target_user.strip()
    if not target:
        return query_my_ratemin_todos(platform=normalized_platform, user_id=requester_user_id, query=query, source_db=source_db, limit=limit)
    resolved = _resolve_im_user(normalized_platform, target)
    if not resolved:
        return {"platform": normalized_platform, "user_id": "", "count": 0, "items": [], "message": f"未找到目标用户：{target_user}"}
    if resolved.get("ambiguous"):
        names = "、".join(str(item.get("name") or item.get("user_id")) for item in resolved.get("matches", [])[:5])
        return {"platform": normalized_platform, "user_id": "", "count": 0, "items": [], "message": f"目标用户不唯一：{target_user}。匹配到：{names}"}
    target_user_id = str(resolved["user_id"])
    if target_user_id != requester_user_id and not _is_platform_admin(normalized_platform, requester_user_id):
        return {"platform": normalized_platform, "user_id": target_user_id, "count": 0, "items": [], "message": "你当前没有管理员权限，不能查询其他人的业务系统待办。"}
    result = query_my_ratemin_todos(
        platform=normalized_platform,
        user_id=target_user_id,
        query=query,
        source_db=source_db,
        limit=limit,
    )
    display_name = str(resolved.get("name") or target_user_id)
    result["message"] = _format_target_todo_query_message(
        items=result.get("items", []),
        display_name=display_name,
        query=query,
        source_db=source_db,
        raw_message=str(result.get("message") or ""),
    )
    return result


def format_ratemin_todos_for_target(
    *,
    platform: str,
    requester_user_id: str,
    target_user: str,
    query: str = "",
    source_db: str = "",
    limit: int = 20,
) -> str:
    result = query_ratemin_todos_for_target(
        platform=platform,
        requester_user_id=requester_user_id,
        target_user=target_user,
        query=query,
        source_db=source_db,
        limit=limit,
    )
    return str(result.get("message") or "")


def flush_pending_ratemin_notifications(platform: str = DEFAULT_PLATFORM, *, limit: int = 100) -> dict[str, Any]:
    conn = _conn()
    normalized_platform = _normalize_platform(platform)
    rows = conn.execute(
        """
        SELECT *
        FROM ratemin_pending_events
        WHERE target_platform = ? AND delivery_status IN ('ready', 'send_failed', 'no_active_ai_assistant')
          AND target_user_id != ''
        ORDER BY created_at
        LIMIT ?
        """,
        (normalized_platform, int(limit)),
    ).fetchall()
    sent = 0
    failed = 0
    checked = 0
    for row in rows:
        event = _row_dict(row)
        if not _assistant_allows_notification(normalized_platform, str(event.get("target_user_id") or "")):
            if event.get("delivery_status") == "ready":
                _mark_event_delivery(conn, event, "no_active_ai_assistant", "employee AI assistant is not active")
            continue
        checked += 1
        ok = _send_event_notification(event)
        _mark_event_delivery(conn, event, "sent" if ok else "send_failed", "" if ok else "provider_outbound returned false")
        sent += 1 if ok else 0
        failed += 0 if ok else 1
    return {"platform": normalized_platform, "checked": checked, "sent": sent, "failed": failed}


def run_ratemin_pending_notifier(platform: str = DEFAULT_PLATFORM) -> dict[str, Any]:
    return flush_pending_ratemin_notifications(platform=platform)


def on_employee_bot_activated(*, platform: str, user_id: str) -> dict[str, Any]:
    conn = _conn()
    normalized_platform = _normalize_platform(platform)
    display_name = _lookup_im_display_name(conn, normalized_platform, user_id)
    bound = 0
    if display_name:
        bound_result = auto_bind_all_ratemin_users(platform=normalized_platform, query=display_name, limit=200)
        bound = int(bound_result.get("bound", 0) or 0)
    rows = conn.execute(
        """
        SELECT source_db, rate_oper_id
        FROM ratemin_user_bindings
        WHERE platform = ? AND im_user_id = ? AND status = 'active'
        """,
        (normalized_platform, user_id),
    ).fetchall()
    allowed = {(str(row["source_db"]), str(row["rate_oper_id"])) for row in rows}
    readied = 0
    if allowed:
        event_rows = conn.execute(
            """
            SELECT *
            FROM ratemin_pending_events
            WHERE target_platform = ? AND target_user_id = ? AND delivery_status = 'no_active_ai_assistant'
            ORDER BY created_at
            """,
            (normalized_platform, user_id),
        ).fetchall()
        for row in event_rows:
            key = (str(row["source_db"]), str(row["recipient_oper_id"]))
            if key not in allowed:
                continue
            conn.execute(
                """
                UPDATE ratemin_pending_events
                SET delivery_status = 'ready', delivery_error = '', updated_at = ?
                WHERE source_db = ? AND event_id = ? AND recipient_oper_id = ?
                """,
                (time.time(), row["source_db"], row["event_id"], row["recipient_oper_id"]),
            )
            readied += 1
        conn.commit()
    sent_result = flush_pending_ratemin_notifications(normalized_platform, limit=200)
    return {
        "platform": normalized_platform,
        "user_id": user_id,
        "auto_bound": bound,
        "readied": readied,
        "sent": int(sent_result.get("sent", 0) or 0),
        "failed": int(sent_result.get("failed", 0) or 0),
    }


def verify_ratemin_ingest_token(token: str) -> bool:
    expected = os.environ.get("RATEMIN_INGEST_TOKEN", "").strip()
    return bool(expected) and _constant_time_equal(token.strip(), expected)


def _conn():
    conn = Database.get().connect()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ratemin_user_snapshot (
            source_db TEXT NOT NULL,
            rate_oper_id TEXT NOT NULL,
            rate_login_name TEXT NOT NULL DEFAULT '',
            rate_display_name TEXT NOT NULL DEFAULT '',
            normalized_display_name TEXT NOT NULL DEFAULT '',
            updated_at REAL NOT NULL,
            PRIMARY KEY (source_db, rate_oper_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ratemin_user_bindings (
            source_db TEXT NOT NULL,
            rate_oper_id TEXT NOT NULL,
            rate_login_name TEXT NOT NULL DEFAULT '',
            rate_display_name TEXT NOT NULL DEFAULT '',
            platform TEXT NOT NULL DEFAULT 'wecom',
            im_user_id TEXT NOT NULL DEFAULT '',
            im_display_name TEXT NOT NULL DEFAULT '',
            match_method TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            created_by TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (source_db, rate_oper_id, platform)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ratemin_pending_events (
            source_db TEXT NOT NULL,
            event_id TEXT NOT NULL,
            flow_id TEXT NOT NULL DEFAULT '',
            flow_post_id TEXT NOT NULL DEFAULT '',
            data_id TEXT NOT NULL DEFAULT '',
            task_id TEXT NOT NULL DEFAULT '',
            flow_name TEXT NOT NULL DEFAULT '',
            recipient_oper_id TEXT NOT NULL DEFAULT '',
            recipient_login_name TEXT NOT NULL DEFAULT '',
            recipient_name TEXT NOT NULL DEFAULT '',
            subject TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL DEFAULT '',
            initiator_login_name TEXT NOT NULL DEFAULT '',
            initiator_name TEXT NOT NULL DEFAULT '',
            todo_time TEXT NOT NULL DEFAULT '',
            received_at TEXT NOT NULL DEFAULT '',
            target_platform TEXT NOT NULL DEFAULT 'wecom',
            target_user_id TEXT NOT NULL DEFAULT '',
            delivery_status TEXT NOT NULL DEFAULT '',
            delivery_error TEXT NOT NULL DEFAULT '',
            fingerprint TEXT NOT NULL DEFAULT '',
            raw_json TEXT NOT NULL DEFAULT '{}',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (source_db, event_id, recipient_oper_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ratemin_current_events (
            source_db TEXT NOT NULL,
            event_id TEXT NOT NULL,
            recipient_oper_id TEXT NOT NULL DEFAULT '',
            target_platform TEXT NOT NULL DEFAULT 'wecom',
            current_status TEXT NOT NULL DEFAULT 'active',
            updated_at REAL NOT NULL,
            PRIMARY KEY (source_db, event_id, recipient_oper_id, target_platform)
        )
        """
    )
    conn.commit()
    return conn


def _normalize_event(raw: dict[str, Any], platform: str) -> dict[str, Any]:
    source_db = _normalize_source_db(str(raw.get("source_db") or raw.get("database") or ""))
    recipient_oper_id = str(raw.get("recipient_oper_id") or raw.get("oper_id") or raw.get("receiver_oper_id") or "").strip()
    if not recipient_oper_id:
        raise ValueError("业务系统事件缺少 recipient_oper_id")
    flow_id = str(raw.get("flow_id") or raw.get("FlowID") or "").strip()
    flow_post_id = str(raw.get("flow_post_id") or raw.get("FlowPostID") or "").strip()
    data_id = str(raw.get("data_id") or raw.get("DataID") or "").strip()
    task_id = str(raw.get("task_id") or raw.get("taskID") or "").strip()
    event_id = str(raw.get("event_id") or "").strip() or _event_id(source_db, flow_id, flow_post_id, data_id, task_id, recipient_oper_id)
    now_text = str(raw.get("received_at") or _now_text())
    subject = str(raw.get("subject") or raw.get("sSubject") or "").strip()
    content = str(raw.get("content") or raw.get("sDesc") or "").strip()
    event = {
        "source_db": source_db,
        "event_id": event_id,
        "flow_id": flow_id,
        "flow_post_id": flow_post_id,
        "data_id": data_id,
        "task_id": task_id,
        "flow_name": str(raw.get("flow_name") or raw.get("flowCaption") or "").strip(),
        "recipient_oper_id": recipient_oper_id,
        "recipient_login_name": str(raw.get("recipient_login_name") or raw.get("recv_login_name") or "").strip(),
        "recipient_name": str(raw.get("recipient_name") or raw.get("recv_name") or "").strip(),
        "subject": subject,
        "content": content,
        "initiator_login_name": str(raw.get("initiator_login_name") or raw.get("starter_login_name") or "").strip(),
        "initiator_name": str(raw.get("initiator_name") or raw.get("starter_name") or "").strip(),
        "todo_time": str(raw.get("todo_time") or raw.get("HasHintTime") or "").strip(),
        "received_at": now_text,
        "target_platform": platform,
        "target_user_id": "",
        "delivery_status": "",
        "delivery_error": "",
        "fingerprint": "",
        "raw_json": json.dumps(raw, ensure_ascii=False, default=str),
    }
    event["fingerprint"] = hashlib.sha256(
        json.dumps(
            {k: event.get(k, "") for k in ("source_db", "event_id", "recipient_oper_id", "subject", "content", "todo_time")},
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return event


def _upsert_user_snapshot(conn: Any, event: dict[str, Any]) -> None:
    now = time.time()
    conn.execute(
        """
        INSERT INTO ratemin_user_snapshot
            (source_db, rate_oper_id, rate_login_name, rate_display_name, normalized_display_name, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_db, rate_oper_id) DO UPDATE SET
            rate_login_name = excluded.rate_login_name,
            rate_display_name = excluded.rate_display_name,
            normalized_display_name = excluded.normalized_display_name,
            updated_at = excluded.updated_at
        """,
        (
            event["source_db"],
            event["recipient_oper_id"],
            event["recipient_login_name"],
            event["recipient_name"],
            _normalize_person_name(event["recipient_name"]),
            now,
        ),
    )
    conn.commit()


def _upsert_snapshot_user(conn: Any, user: dict[str, str]) -> None:
    conn.execute(
        """
        INSERT INTO ratemin_user_snapshot
            (source_db, rate_oper_id, rate_login_name, rate_display_name, normalized_display_name, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_db, rate_oper_id) DO UPDATE SET
            rate_login_name = excluded.rate_login_name,
            rate_display_name = excluded.rate_display_name,
            normalized_display_name = excluded.normalized_display_name,
            updated_at = excluded.updated_at
        """,
        (
            user["source_db"],
            user["rate_oper_id"],
            user["rate_login_name"],
            user["rate_display_name"],
            _normalize_person_name(user["rate_display_name"]),
            time.time(),
        ),
    )
    conn.commit()


def _resolve_binding(conn: Any, event: dict[str, Any], platform: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT *
        FROM ratemin_user_bindings
        WHERE source_db = ? AND rate_oper_id = ? AND platform = ? AND status = 'active'
        """,
        (event["source_db"], event["recipient_oper_id"], platform),
    ).fetchone()
    if row:
        return _row_dict(row)
    return _auto_bind_by_display_name(conn, event, platform)


def _auto_bind_by_display_name(conn: Any, event: dict[str, Any], platform: str) -> dict[str, Any] | None:
    normalized = _normalize_person_name(event["recipient_name"])
    if not normalized:
        return None
    matches = _org_user_matches(conn, platform, normalized)
    if len(matches) != 1:
        return None
    row = matches[0]
    return bind_ratemin_user(
        source_db=event["source_db"],
        rate_oper_id=event["recipient_oper_id"],
        rate_login_name=event["recipient_login_name"],
        rate_display_name=event["recipient_name"],
        platform=platform,
        im_user_id=str(row["user_id"]),
        im_display_name=str(row["name"]),
        created_by="auto-display-name",
        match_method="auto-display-name",
    )


def _auto_bind_snapshot_user(conn: Any, user: dict[str, str], platform: str) -> str:
    row = conn.execute(
        """
        SELECT im_user_id, status, match_method
        FROM ratemin_user_bindings
        WHERE source_db = ? AND rate_oper_id = ? AND platform = ?
        """,
        (user["source_db"], user["rate_oper_id"], platform),
    ).fetchone()
    if row and str(row["im_user_id"] or ""):
        return "skip"
    normalized = _normalize_person_name(user["rate_display_name"])
    if not normalized:
        return "unmatched"
    matches = _org_user_matches(conn, platform, normalized)
    if len(matches) == 1:
        match = matches[0]
        bind_ratemin_user(
            source_db=user["source_db"],
            rate_oper_id=user["rate_oper_id"],
            rate_login_name=user["rate_login_name"],
            rate_display_name=user["rate_display_name"],
            platform=platform,
            im_user_id=str(match["user_id"]),
            im_display_name=str(match["name"]),
            created_by="auto-display-name",
            match_method="auto-display-name",
        )
        return "bound"
    if len(matches) > 1:
        return "ambiguous"
    return "unmatched"


def _initial_delivery_status(binding: dict[str, Any] | None, platform: str) -> str:
    if not binding:
        return "unmatched"
    user_id = str(binding.get("im_user_id") or "")
    if not _assistant_allows_notification(platform, user_id):
        return "no_active_ai_assistant"
    return "ready"


def _assistant_allows_notification(platform: str, user_id: str) -> bool:
    conn = Database.get().connect()
    try:
        row = conn.execute(
            """
            SELECT status
            FROM employee_bot_assignments
            WHERE platform = ? AND user_id = ?
            """,
            (platform, user_id),
        ).fetchone()
    except Exception:
        return False
    if not row:
        return False
    return str(row["status"] or "") == "active"


def _send_event_notification(event: dict[str, Any]) -> bool:
    text = _format_notification(event)
    return provider_outbound.send_platform_text(event.get("target_platform") or DEFAULT_PLATFORM, event["target_user_id"], text)


def _format_notification(event: dict[str, Any]) -> str:
    lines = [
        f"[业务系统 {event.get('source_db')}]",
        f"主题：{event.get('subject') or event.get('flow_name') or '待办'}",
        f"内容：{event.get('content') or '请尽快处理'}",
        f"接收人：{_short_name(event.get('recipient_name', ''))}",
    ]
    if event.get("todo_time"):
        lines.append(f"待办时间：{event.get('todo_time')}")
    if event.get("received_at"):
        lines.append(f"收到时间：{event.get('received_at')}")
    if event.get("initiator_name") or event.get("initiator_login_name"):
        starter = _short_name(event.get("initiator_name", "")) or event.get("initiator_login_name")
        lines.append(f"流程发起人：{starter}")
    lines.append("可回复“查询我的业务系统待办”查看清单；AI 助手只查询和提醒，不代办审批。")
    return "\n".join(lines)


def _format_todo_query_message(items: list[dict[str, Any]], *, query: str, source_db: str) -> str:
    if not items:
        scope = f"{source_db} " if source_db else ""
        keyword = f"关键词“{query}”" if query else ""
        return f"当前没有找到{scope}{keyword}相关的业务系统待办。"
    lines = [f"你当前有 {len(items)} 条业务系统待办："]
    for item in items[:20]:
        title = item.get("subject") or item.get("flow_name") or "待办"
        starter = _short_name(str(item.get("initiator_name") or "")) or str(item.get("initiator_login_name") or "")
        tail = f"，发起人：{starter}" if starter else ""
        lines.append(
            f"- [业务系统 {item.get('source_db')}] {title}：{item.get('content') or '请尽快处理'}，"
            f"待办时间：{item.get('todo_time') or '-'}{tail}"
        )
    lines.append("说明：这里只能查询和提醒你的业务系统待办，不会在业务系统里发起、同意、退回或处理流程。")
    return "\n".join(lines)


def _format_target_todo_query_message(
    *,
    items: list[dict[str, Any]],
    display_name: str,
    query: str,
    source_db: str,
    raw_message: str,
) -> str:
    if raw_message.startswith("未找到目标用户") or raw_message.startswith("目标用户不唯一") or raw_message.startswith("你当前没有管理员权限"):
        return raw_message
    if not items:
        scope = f"{source_db} " if source_db else ""
        keyword = f"关键词“{query}”" if query else ""
        return f"{display_name} 当前没有找到{scope}{keyword}相关的业务系统待办。"
    lines = [f"{display_name} 当前有 {len(items)} 条业务系统待办："]
    for item in items[:20]:
        title = item.get("subject") or item.get("flow_name") or "待办"
        starter = _short_name(str(item.get("initiator_name") or "")) or str(item.get("initiator_login_name") or "")
        tail = f"，发起人：{starter}" if starter else ""
        lines.append(
            f"- [业务系统 {item.get('source_db')}] {title}：{item.get('content') or '请尽快处理'}，"
            f"待办时间：{item.get('todo_time') or '-'}{tail}"
        )
    lines.append("说明：这里只提供业务系统待办查询和提醒，不会代办业务系统流程。")
    return "\n".join(lines)


def _insert_event(conn: Any, event: dict[str, Any]) -> None:
    now = time.time()
    values = {**event, "created_at": now, "updated_at": now}
    columns = [
        "source_db", "event_id", "flow_id", "flow_post_id", "data_id", "task_id", "flow_name",
        "recipient_oper_id", "recipient_login_name", "recipient_name", "subject", "content",
        "initiator_login_name", "initiator_name", "todo_time", "received_at", "target_platform",
        "target_user_id", "delivery_status", "delivery_error", "fingerprint", "raw_json",
        "created_at", "updated_at",
    ]
    conn.execute(
        f"INSERT INTO ratemin_pending_events ({','.join(columns)}) VALUES ({','.join(['?'] * len(columns))})",
        tuple(values.get(col, "") for col in columns),
    )
    conn.commit()


def _update_event(conn: Any, event: dict[str, Any], *, existing_status: str = "") -> None:
    delivery_status = existing_status if existing_status == "sent" else event["delivery_status"]
    conn.execute(
        """
        UPDATE ratemin_pending_events
        SET subject = ?, content = ?, flow_name = ?, initiator_login_name = ?, initiator_name = ?,
            todo_time = ?, received_at = ?, target_user_id = ?, delivery_status = ?,
            fingerprint = ?, raw_json = ?, updated_at = ?
        WHERE source_db = ? AND event_id = ? AND recipient_oper_id = ?
        """,
        (
            event["subject"],
            event["content"],
            event["flow_name"],
            event["initiator_login_name"],
            event["initiator_name"],
            event["todo_time"],
            event["received_at"],
            event["target_user_id"],
            delivery_status,
            event["fingerprint"],
            event["raw_json"],
            time.time(),
            event["source_db"],
            event["event_id"],
            event["recipient_oper_id"],
        ),
    )
    conn.commit()


def _mark_event_delivery(conn: Any, event: dict[str, Any], status: str, error: str = "") -> None:
    conn.execute(
        """
        UPDATE ratemin_pending_events
        SET delivery_status = ?, delivery_error = ?, updated_at = ?
        WHERE source_db = ? AND event_id = ? AND recipient_oper_id = ?
        """,
        (status, error, time.time(), event["source_db"], event["event_id"], event["recipient_oper_id"]),
    )
    conn.commit()


def _event_row(conn: Any, source_db: str, event_id: str, recipient_oper_id: str) -> Any:
    return conn.execute(
        """
        SELECT *
        FROM ratemin_pending_events
        WHERE source_db = ? AND event_id = ? AND recipient_oper_id = ?
        """,
        (source_db, event_id, recipient_oper_id),
    ).fetchone()


def _lookup_im_display_name(conn: Any, platform: str, user_id: str) -> str:
    row = conn.execute("SELECT name FROM org_users WHERE platform = ? AND user_id = ?", (platform, user_id)).fetchone()
    return str(row["name"]) if row else ""


def _resolve_im_user(platform: str, target: str) -> dict[str, Any] | None:
    conn = Database.get().connect()
    raw = target.strip()
    if not raw:
        return None
    row = conn.execute(
        "SELECT user_id, name FROM org_users WHERE platform = ? AND user_id = ?",
        (platform, raw),
    ).fetchone()
    if row:
        return {"user_id": str(row["user_id"]), "name": str(row["name"]), "ambiguous": False}
    exact = conn.execute(
        "SELECT user_id, name FROM org_users WHERE platform = ? AND name = ? ORDER BY name, user_id",
        (platform, raw),
    ).fetchall()
    if len(exact) == 1:
        row = exact[0]
        return {"user_id": str(row["user_id"]), "name": str(row["name"]), "ambiguous": False}
    if len(exact) > 1:
        return {"ambiguous": True, "matches": [_row_dict(row) for row in exact]}
    like = conn.execute(
        "SELECT user_id, name FROM org_users WHERE platform = ? AND name LIKE ? ORDER BY name, user_id LIMIT 10",
        (platform, f"%{raw}%"),
    ).fetchall()
    if len(like) == 1:
        row = like[0]
        return {"user_id": str(row["user_id"]), "name": str(row["name"]), "ambiguous": False}
    if len(like) > 1:
        return {"ambiguous": True, "matches": [_row_dict(row) for row in like]}
    return None


def _org_user_matches(conn: Any, platform: str, normalized_name: str) -> list[Any]:
    rows = conn.execute(
        """
        SELECT user_id, name
        FROM org_users
        WHERE platform = ?
        """,
        (platform,),
    ).fetchall()
    return [row for row in rows if _normalize_person_name(str(row["name"])) == normalized_name]


def _normalize_snapshot_user(raw: dict[str, Any]) -> dict[str, str]:
    source_db = _normalize_source_db(str(raw.get("source_db") or raw.get("database") or ""))
    rate_oper_id = str(raw.get("rate_oper_id") or raw.get("oper_id") or raw.get("OperID") or "").strip()
    if not rate_oper_id:
        raise ValueError("业务系统用户快照缺少 rate_oper_id")
    return {
        "source_db": source_db,
        "rate_oper_id": rate_oper_id,
        "rate_login_name": str(raw.get("rate_login_name") or raw.get("login_name") or raw.get("LoginName") or "").strip(),
        "rate_display_name": str(raw.get("rate_display_name") or raw.get("display_name") or raw.get("sName") or "").strip(),
    }


def _is_platform_admin(platform: str, user_id: str) -> bool:
    try:
        from src.web.admin_auth import is_platform_admin

        return is_platform_admin(platform, user_id)
    except Exception:
        return False


def _normalize_person_name(value: str) -> str:
    text = str(value or "").strip()
    text = text.split("_", 1)[0]
    text = re.sub(r"\s+", "", text)
    return text.lower()


def _short_name(value: str) -> str:
    return str(value or "").split("_", 1)[0].strip()


def _normalize_platform(platform: str) -> str:
    lowered = str(platform or DEFAULT_PLATFORM).strip().lower()
    return {"wecom_bot": "wecom", "wecom_bot_ws": "wecom", "企微": "wecom", "企业微信": "wecom"}.get(lowered, lowered or DEFAULT_PLATFORM)


def _normalize_source_db(source_db: str) -> str:
    text = str(source_db or "").strip().lower()
    if text not in set(configured_source_dbs()):
        raise ValueError(f"不支持的业务系统数据库：{source_db}")
    return text


def _event_id(source_db: str, flow_id: str, flow_post_id: str, data_id: str, task_id: str, recipient_oper_id: str) -> str:
    raw = f"{source_db}:{flow_id}:{flow_post_id}:{data_id}:{task_id}:{recipient_oper_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _now_text() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _row_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    return {key: row[key] for key in row.keys()}


def _constant_time_equal(left: str, right: str) -> bool:
    return hashlib.sha256(left.encode()).digest() == hashlib.sha256(right.encode()).digest()
