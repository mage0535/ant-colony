from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any

from src.gateway import provider_outbound
from src.platform import build_capability_context, invoke_capability
from src.store.database import Database


def run_process_change_notifier(platform: str = "wecom", *, dry_run: bool = False) -> dict[str, Any]:
    """Poll enterprise app / approval / process state and notify affected users."""
    normalized_platform = _normalize_platform(platform)
    conn = _conn()
    active_users = _active_ai_assistant_users(conn, normalized_platform)
    checked = 0
    notified = 0
    changed = 0
    errors: list[str] = []

    for user_id in active_users:
        try:
            items, load_error = _load_user_process_items(normalized_platform, user_id)
            if load_error:
                errors.append(f"{user_id}:{load_error}")
            checked += len(items)
            for item in items:
                outcome = _record_and_notify_for_recipient(conn, normalized_platform, user_id, item, dry_run=dry_run)
                if outcome == "changed":
                    changed += 1
                    notified += 1
                elif outcome == "delivery_failed":
                    errors.append(f"{user_id}:通知投递失败，后续会自动重试")
        except Exception as exc:
            errors.append(f"{user_id}:{exc}")

    return {
        "platform": normalized_platform,
        "users": len(active_users),
        "checked": checked,
        "changed": changed,
        "notified": notified,
        "dry_run": bool(dry_run),
        "errors": errors[:20],
    }


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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS process_notification_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            user_id TEXT NOT NULL,
            source TEXT NOT NULL,
            item_id TEXT NOT NULL,
            action TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS process_status_snapshots (
            platform TEXT NOT NULL,
            applicant_user_id TEXT NOT NULL,
            source TEXT NOT NULL,
            item_id TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT '',
            current_node TEXT NOT NULL DEFAULT '',
            fingerprint TEXT NOT NULL DEFAULT '',
            snapshot_json TEXT NOT NULL DEFAULT '{}',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (platform, applicant_user_id, source, item_id)
        )
        """
    )
    conn.commit()
    return conn


def _active_ai_assistant_users(conn: Any, platform: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT user_id
        FROM employee_bot_assignments
        WHERE platform = ? AND status = 'active'
        ORDER BY user_id
        """,
        (platform,),
    ).fetchall()
    return [str(row["user_id"]) for row in rows]


def _load_user_process_items(platform: str, user_id: str) -> tuple[list[dict[str, Any]], str]:
    structured, structured_error = _load_structured_process_items(platform, user_id)
    if structured:
        return structured, ""
    context = build_capability_context(user_id=user_id, platform=platform, scope="personal")
    text = invoke_capability("approval.list", "all", context=context, empty_message="")
    fallback_items = _parse_approval_text(text, applicant_user_id=user_id)
    return fallback_items, _safe_wecom_error(structured_error) if structured_error and not fallback_items else ""


def _load_structured_process_items(platform: str, user_id: str) -> tuple[list[dict[str, Any]], str]:
    if platform != "wecom":
        return [], ""
    try:
        from src.platform.api_wecom import WeComClient

        client = WeComClient()
        method = getattr(client, "list_process_events", None)
        if not callable(method):
            return [], ""
        context = build_capability_context(user_id=user_id, platform=platform, scope="personal")
        result = method(capability_context=context)
        items = list(result or []) if isinstance(result, list) else []
        error = str(getattr(client, "last_process_event_error", "") or "")
        if error:
            return items, _safe_wecom_error(error)
        return items, ""
    except Exception as exc:
        return [], _safe_wecom_error(str(exc))


def _parse_approval_text(text: str, *, applicant_user_id: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    pattern = re.compile(
        r"(?P<title>.+?)（(?P<id>[^）]+)）：(?P<status>[^，]+)，申请人\s*(?P<applicant>.+?)(?:，当前节点\s*(?P<node>.+))?$"
    )
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("[") or "申请人" not in line:
            continue
        match = pattern.match(line)
        if match:
            title = match.group("title").strip()
            item_id = match.group("id").strip()
            status = match.group("status").strip()
            applicant = match.group("applicant").strip()
            current_node = (match.group("node") or "").strip()
        else:
            title = line.split("，", 1)[0].strip()
            item_id = hashlib.sha256(line.encode("utf-8")).hexdigest()[:16]
            status = _extract_after(line, "：", "，") or ""
            applicant = applicant_user_id
            current_node = _extract_after(line, "当前节点", "，") or ""
        items.append(
            {
                "source": "approval",
                "item_id": item_id,
                "title": title,
                "status": status,
                "current_node": current_node,
                "applicant_user_id": applicant_user_id,
                "applicant_name": applicant,
                "recipient_user_ids": [],
                "content": title,
                "event_time": "",
            }
        )
    return items


def _record_and_notify_for_recipient(conn: Any, platform: str, recipient_user_id: str, item: dict[str, Any], *, dry_run: bool = False) -> str:
    applicant_user_id = str(item.get("applicant_user_id") or "")
    current_handlers = {str(uid) for uid in item.get("recipient_user_ids", []) if str(uid)}
    if recipient_user_id == applicant_user_id:
        role = "applicant"
    elif recipient_user_id in current_handlers:
        role = "handler"
    else:
        return "not_relevant"

    snapshot_item = {**item, "notification_role": role, "recipient_user_id": recipient_user_id}
    snapshot_key = _snapshot_key(snapshot_item)
    fingerprint = _fingerprint(snapshot_item)
    now = time.time()
    row = conn.execute(
        """
        SELECT fingerprint, status, current_node
        FROM process_status_snapshots
        WHERE platform = ? AND applicant_user_id = ? AND source = ? AND item_id = ?
        """,
        (platform, recipient_user_id, snapshot_item["source"], snapshot_key),
    ).fetchone()

    if not row:
        if dry_run:
            return "changed" if role == "handler" else "created"
        if role == "handler":
            text = _build_notification(snapshot_item, old_status="", old_node="", first_assignment=True)
            if not provider_outbound.send_platform_text(platform, recipient_user_id, text):
                _record_audit(conn, platform, recipient_user_id, snapshot_item, "delivery_failed", "消息通道返回失败，将在下一轮重试")
                return "delivery_failed"
            _insert_snapshot(conn, platform, recipient_user_id, snapshot_item, snapshot_key, fingerprint, now)
            _record_audit(conn, platform, recipient_user_id, snapshot_item, "sent", "流程到达当前处理人，已通知")
            return "changed"
        _insert_snapshot(conn, platform, recipient_user_id, snapshot_item, snapshot_key, fingerprint, now)
        _record_audit(conn, platform, recipient_user_id, snapshot_item, "baseline", "首次读取申请人流程状态，不推送历史记录")
        return "created"

    if str(row["fingerprint"]) == fingerprint:
        if not dry_run:
            _record_audit(conn, platform, recipient_user_id, snapshot_item, "unchanged", "状态未变化，跳过推送")
        return "unchanged"

    if _is_parser_repair_change(row, snapshot_item):
        if dry_run:
            return "unchanged"
        _update_snapshot(conn, platform, recipient_user_id, snapshot_item, snapshot_key, fingerprint, now)
        _record_audit(conn, platform, recipient_user_id, snapshot_item, "parser_repaired", "修正旧解析产生的数字节点或未来节点快照，不推送提醒")
        return "unchanged"

    if dry_run:
        return "changed"

    old_status = str(row["status"] or "")
    old_node = str(row["current_node"] or "")
    text = _build_notification(snapshot_item, old_status=old_status, old_node=old_node, first_assignment=False)
    if not provider_outbound.send_platform_text(platform, recipient_user_id, text):
        _record_audit(conn, platform, recipient_user_id, snapshot_item, "delivery_failed", "消息通道返回失败，将在下一轮重试")
        return "delivery_failed"
    _update_snapshot(conn, platform, recipient_user_id, snapshot_item, snapshot_key, fingerprint, now)
    _record_audit(conn, platform, recipient_user_id, snapshot_item, "sent", "流程状态或节点变更已通知")
    return "changed"


def _update_snapshot(conn: Any, platform: str, recipient_user_id: str, item: dict[str, Any], snapshot_key: str, fingerprint: str, now: float) -> None:
    conn.execute(
        """
        UPDATE process_status_snapshots
        SET title = ?, status = ?, current_node = ?, fingerprint = ?, snapshot_json = ?, updated_at = ?
        WHERE platform = ? AND applicant_user_id = ? AND source = ? AND item_id = ?
        """,
        (
            str(item.get("title", "")),
            str(item.get("status", "")),
            str(item.get("current_node", "")),
            fingerprint,
            json.dumps(item, ensure_ascii=False),
            now,
            platform,
            recipient_user_id,
            item["source"],
            snapshot_key,
        ),
    )
    conn.commit()


def _is_parser_repair_change(row: Any, item: dict[str, Any]) -> bool:
    old_status = str(row["status"] or "")
    new_status = str(item.get("status", "") or "")
    old_node = str(row["current_node"] or "").strip()
    new_node = str(item.get("current_node", "") or "").strip()
    role = str(item.get("notification_role") or "")
    if role != "applicant" or old_status != new_status:
        return False
    if old_node in {"1", "2", "3", "4", "6", "7", "10"} and old_node != new_node:
        return True
    return False


def _insert_snapshot(conn: Any, platform: str, recipient_user_id: str, item: dict[str, Any], snapshot_key: str, fingerprint: str, now: float) -> None:
    conn.execute(
        """
        INSERT INTO process_status_snapshots
            (platform, applicant_user_id, source, item_id, title, status, current_node, fingerprint, snapshot_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            platform,
            recipient_user_id,
            item["source"],
            snapshot_key,
            str(item.get("title", "")),
            str(item.get("status", "")),
            str(item.get("current_node", "")),
            fingerprint,
            json.dumps(item, ensure_ascii=False),
            now,
            now,
        ),
    )
    conn.commit()


def _build_notification(item: dict[str, Any], *, old_status: str, old_node: str, first_assignment: bool) -> str:
    role = str(item.get("notification_role") or "")
    header = "【流程待办提醒】" if first_assignment or role == "handler" else "【流程状态变更】"
    lines = [
        header,
        f"流程：{item.get('title') or '审批/流程'}",
        f"发起人：{item.get('applicant_name') or item.get('applicant_user_id') or '未知'}",
    ]
    if item.get("event_time"):
        lines.append(f"日期时间：{item.get('event_time')}")
    if item.get("content"):
        lines.append(f"内容：{item.get('content')}")
    if first_assignment:
        lines.append(f"当前节点：{item.get('current_node') or '待处理'}")
        lines.append(f"状态：{item.get('status') or '未知'}")
    else:
        lines.append(f"状态：{old_status or '未知'} -> {item.get('status') or '未知'}")
        if old_node or item.get("current_node"):
            lines.append(f"当前节点：{old_node or '未知'} -> {item.get('current_node') or '未知'}")
    lines.append("如需查看详情，可以继续问我“查询我的审批状态”。AI 助手只提醒和查询，不代办审批。")
    return "\n".join(lines)


def _record_audit(conn: Any, platform: str, user_id: str, item: dict[str, Any], action: str, detail: str) -> None:
    conn.execute(
        "INSERT INTO process_notification_audit (platform, user_id, source, item_id, action, detail, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (platform, user_id, str(item.get("source", "approval")), str(item.get("item_id", "")), action, detail, time.time()),
    )
    conn.commit()


def _snapshot_key(item: dict[str, Any]) -> str:
    return f"{item.get('source', 'approval')}:{item.get('item_id', '')}:{item.get('notification_role', '')}"


def _fingerprint(item: dict[str, Any]) -> str:
    payload = {
        "status": item.get("status", ""),
        "current_node": item.get("current_node", ""),
        "recipient_user_ids": sorted(str(uid) for uid in item.get("recipient_user_ids", []) if str(uid)),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _extract_after(text: str, start: str, end: str) -> str:
    if start not in text:
        return ""
    tail = text.split(start, 1)[1].lstrip("：: ")
    return tail.split(end, 1)[0].strip()


def _safe_wecom_error(error: str) -> str:
    raw = str(error or "").strip()
    if not raw:
        return ""
    if "corpsecret missing" in raw or "41004" in raw:
        return "企微审批/流程凭据缺失：请检查 WECOM_APPROVAL_SECRET 或 WECOM_SECRET 是否已加载到定时任务服务"
    if "no approval auth" in raw or "48002" in raw or "api forbidden" in raw.lower():
        return "企微审批/流程权限不足：请检查 AI 助手应用是否具备审批数据读取权限"
    return raw.split(" more info at ", 1)[0].split(", more info at ", 1)[0][:200]


def _normalize_platform(platform: str) -> str:
    lowered = str(platform or "wecom").strip().lower()
    return {"wecom_bot": "wecom", "wecom_bot_ws": "wecom", "企微": "wecom", "企业微信": "wecom"}.get(lowered, lowered or "wecom")
