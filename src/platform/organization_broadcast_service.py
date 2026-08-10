from __future__ import annotations

from typing import Any

from src.store.database import Database


class OrganizationBroadcastError(ValueError):
    pass


def broadcast_to_organization(
    *,
    platform: str = "wecom",
    sender_user_id: str,
    target: str,
    message: str,
) -> dict[str, Any]:
    normalized_platform = _normalize_platform(platform)
    sender = (sender_user_id or "").strip()
    target_text = (target or "").strip()
    content = (message or "").strip()
    if not sender:
        raise OrganizationBroadcastError("缺少发送人企业 IM 用户 ID")
    if not target_text:
        raise OrganizationBroadcastError("缺少通知目标组织范围")
    if not content:
        raise OrganizationBroadcastError("缺少通知内容")
    if not _is_admin(normalized_platform, sender):
        raise PermissionError("当前企业 IM 用户不是管理员")

    conn = Database.get().connect()
    target_info, target_user_ids = _resolve_target_users(conn, normalized_platform, target_text)
    target_user_ids = [user_id for user_id in target_user_ids if user_id != sender]
    active_assignments = _list_active_assignments(conn, normalized_platform)
    active_user_ids = {row["user_id"] for row in active_assignments}
    recipients = sorted(user_id for user_id in target_user_ids if user_id in active_user_ids)
    skipped = max(0, len(target_user_ids) - len(recipients))

    from src.gateway import provider_outbound

    sent = 0
    failed: list[str] = []
    for user_id in recipients:
        if provider_outbound.send_platform_text(normalized_platform, user_id, content):
            sent += 1
        else:
            failed.append(user_id)

    return {
        "ok": not failed,
        "platform": normalized_platform,
        "sender_user_id": sender,
        "target": target_info,
        "message": content,
        "matched": len(target_user_ids),
        "eligible": len(recipients),
        "sent": sent,
        "failed": len(failed),
        "failed_user_ids": failed,
        "skipped": skipped + len(failed),
        "recipient_user_ids": recipients,
    }


def _resolve_target_users(conn: Any, platform: str, target: str) -> tuple[dict[str, str], list[str]]:
    if target in {"全体员工", "全员", "全公司", "公司", "organization", "*"}:
        rows = conn.execute(
            """
            SELECT user_id
            FROM org_users
            WHERE platform = ?
            ORDER BY user_id
            """,
            (platform,),
        ).fetchall()
        return {"type": "organization", "id": "*", "name": "全体员工"}, [str(row["user_id"]) for row in rows]

    dept = _find_department(conn, platform, target)
    if dept is None:
        raise OrganizationBroadcastError(f"未找到组织范围：{target}")
    dept_ids = _department_with_descendants(conn, platform, str(dept["dept_id"]))
    placeholders = ",".join("?" for _ in dept_ids)
    rows = conn.execute(
        f"""
        SELECT DISTINCT user_id
        FROM org_memberships
        WHERE platform = ? AND dept_id IN ({placeholders})
        ORDER BY user_id
        """,
        [platform, *dept_ids],
    ).fetchall()
    return (
        {"type": "department", "id": str(dept["dept_id"]), "name": str(dept["name"])},
        [str(row["user_id"]) for row in rows],
    )


def _find_department(conn: Any, platform: str, target: str) -> Any | None:
    row = conn.execute(
        """
        SELECT dept_id, name
        FROM org_departments
        WHERE platform = ? AND (dept_id = ? OR name = ?)
        ORDER BY CASE WHEN name = ? THEN 0 ELSE 1 END, dept_id
        LIMIT 1
        """,
        (platform, target, target, target),
    ).fetchone()
    return row


def _department_with_descendants(conn: Any, platform: str, root_dept_id: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT dept_id, parent_dept_id
        FROM org_departments
        WHERE platform = ?
        """,
        (platform,),
    ).fetchall()
    children: dict[str, list[str]] = {}
    for row in rows:
        children.setdefault(str(row["parent_dept_id"] or ""), []).append(str(row["dept_id"]))
    result: list[str] = []
    stack = [root_dept_id]
    seen: set[str] = set()
    while stack:
        dept_id = stack.pop()
        if dept_id in seen:
            continue
        seen.add(dept_id)
        result.append(dept_id)
        stack.extend(children.get(dept_id, []))
    return result


def _list_active_assignments(conn: Any, platform: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT user_id
        FROM employee_bot_assignments
        WHERE platform = ? AND status = 'active'
        ORDER BY user_id
        """,
        (platform,),
    ).fetchall()
    return [{"user_id": str(row["user_id"])} for row in rows]


def _is_admin(platform: str, user_id: str) -> bool:
    try:
        from src.web.admin_auth import is_platform_admin

        return is_platform_admin(platform, user_id)
    except Exception:
        return False


def _normalize_platform(platform: str) -> str:
    normalized = str(platform or "wecom").strip().lower() or "wecom"
    aliases = {
        "wecom_bot": "wecom",
        "wecom_bot_ws": "wecom",
        "wecom_callback": "wecom",
        "企业微信": "wecom",
        "企微": "wecom",
        "feishu_bot": "feishu",
        "lark": "feishu",
        "lark_bot": "feishu",
        "飞书": "feishu",
        "dingtalk_bot": "dingtalk",
        "钉钉": "dingtalk",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"wecom", "feishu", "dingtalk"}:
        raise OrganizationBroadcastError(f"不支持的平台：{platform}")
    return normalized
