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
        notify_status = send_employee_bot_welcome(
            platform=normalized_platform,
            user_id=normalized_user_id,
            display_name=display_name,
        )["notify_status"]
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
            _normalize_display_name(normalized_platform, display_name),
            scope.strip() or "personal",
            json.dumps(permissions, ensure_ascii=False),
            activated_by,
            notify_status,
            now,
            now,
        ),
    )
    conn.commit()
    try:
        from src.platform.ratemin_service import on_employee_bot_activated

        on_employee_bot_activated(platform=normalized_platform, user_id=normalized_user_id)
    except Exception:
        pass
    return get_employee_bot_assignment(normalized_platform, normalized_user_id) or {}


def send_employee_bot_welcome(*, platform: str, user_id: str, display_name: str = "") -> dict[str, Any]:
    normalized_platform = _normalize_platform(platform)
    normalized_user_id = user_id.strip()
    if not normalized_user_id:
        raise ValueError("缺少员工企业 IM 用户 ID")
    bot_name = _resolve_bot_display_name(normalized_platform, display_name)
    notify_status = _notify_employee(normalized_platform, normalized_user_id, bot_name)
    conn = _conn()
    now = time.time()
    row = conn.execute(
        """
        SELECT platform, user_id
        FROM employee_bot_assignments
        WHERE platform = ? AND user_id = ?
        """,
        (normalized_platform, normalized_user_id),
    ).fetchone()
    if row:
        conn.execute(
            """
            UPDATE employee_bot_assignments
            SET display_name = ?, notify_status = ?, updated_at = ?
            WHERE platform = ? AND user_id = ?
            """,
            (bot_name, notify_status, now, normalized_platform, normalized_user_id),
        )
    conn.commit()
    assignment = get_employee_bot_assignment(normalized_platform, normalized_user_id) or {
        "platform": normalized_platform,
        "user_id": normalized_user_id,
        "display_name": bot_name,
        "status": "not_found",
    }
    return {"notify_status": notify_status, "bot_name": bot_name, "assignment": assignment}


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
        (_normalize_display_name(normalized_platform, display_name), time.time(), normalized_platform, normalized_user_id),
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
    _repair_display_names(conn, rows)
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
    if row:
        _repair_display_names(conn, [row])
    return _row_to_dict(row) if row else None


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "platform": row[0],
        "user_id": row[1],
        "display_name": _normalize_display_name(row[0], row[2]),
        "scope": row[3],
        "permissions": json.loads(row[4] or "[]"),
        "status": row[5],
        "activated_by": row[6],
        "notify_status": row[7],
        "created_at": row[8],
        "updated_at": row[9],
    }


def _notify_employee(platform: str, user_id: str, display_name: str) -> str:
    try:
        from src.gateway import provider_outbound

        bot_name = _resolve_bot_display_name(platform, display_name)
        text = build_employee_bot_welcome_message(bot_name)
        return "sent" if provider_outbound.send_platform_text(platform, user_id, text) else "send_failed"
    except Exception as exc:
        return f"send_error:{exc}"


def build_employee_bot_welcome_message(bot_name: str) -> str:
    name = (bot_name or "").strip() or "企业 AI 助手"
    return (
        f"你的企业 AI 助手已开通：{name}\n\n"
        f"以后你看到的入口都统一叫“企业 AI 助手”。后台会按需要自动衔接应用通知、Bot 会话、群聊 @、文档、待办、知识库和企业系统能力，你不用区分这些技术通道。\n"
        f"你可以直接回复这条消息开始使用；也可以在企业 IM 顶部搜索框搜索，或在群聊里 @：{name}\n\n"
        "我能帮你做什么：\n"
        "1. 知识库问答：查询公司制度、操作说明、部门资料、个人/部门/公司知识库内容，并按你的组织架构权限返回答案。\n"
        "2. 文档处理：读取、总结、优化、改写、生成 Word、Excel、PPT、PDF，支持按模板生成正式文件并直接推送文件。\n"
        "3. 企业应用查询：在你的权限范围内查询审批、流程、会议室、日程、待办、通讯录、企业文档、网盘和已接入的第三方系统数据。\n"
        "4. 审批与流程提醒：你的申请状态变化、流程到达你处理、业务系统待办或其他已接入流程发生变化时，会主动提醒你。\n"
        "5. 业务系统通知与查询：业务系统有新待办、退回或待处理事项会第一时间提醒；你也可以查询自己的业务系统待办清单，并按主题、发起人、时间模糊查找。AI 助手只提醒和查询，不代替你审批。\n"
        "6. 邮件摘要：管理员配置邮箱后，可汇总新邮件的到达时间、发件人、标题、正文摘要和附件名，不会替你发邮件或回复邮件。\n"
        "7. 待办和任务协作：创建待办、查询待办、整理会议事项、拆解任务、生成催办或跟进建议。\n"
        "8. 会议和日程协助：查询日程、会议安排、会议室占用情况，协助整理会议纪要和后续行动项。\n"
        "9. 联网检索：上网查找资料、论文、行业信息、已有 PPT/课件/文档，并给出可点击来源链接和摘要。\n"
        "10. 公共信息订阅：可订阅天气、空气质量、汇率、新闻、节假日、行业信息、物流/航班/供应链价格等提醒。\n"
        "11. 专家角色协助：可选择制度顾问、文档助手、审批流程顾问、会议助理、知识库管理员、数据分析助手等角色来处理不同工作。\n\n"
        "第一次和我聊天时，你可以给我起一个专属名字，也可以选择我的工作角色。示例：\n"
        "“你的名字叫小智，角色选文档与制度顾问。”\n"
        "“以后你叫我韩工，帮我重点处理邮件、审批和资料查询。”\n\n"
        "如果某项能力提示未配置，通常是因为企业微信权限、后台凭据或个人账号还没有开通。你可以把提示截图发给管理员处理。\n\n"
        "说明：此 AI 助手目前处于测试和持续优化阶段。如发现任何问题，或有需要增加的功能、改进想法和使用场景，请联系公司 IT 人员反馈。"
    )


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
    if normalized in {"wecom_bot", "wecom_bot_ws", "wecom_app"}:
        return "wecom"
    if normalized not in {"wecom", "feishu", "dingtalk"}:
        raise ValueError(f"不支持的平台：{platform}")
    return normalized


def _default_bot_name(platform: str) -> str:
    return {
        "wecom": "企业 AI 助手",
        "feishu": "飞书 AI 助手",
        "dingtalk": "钉钉 AI 助手",
    }.get(platform, "企业 AI 助手")


def _resolve_bot_display_name(platform: str, display_name: str = "") -> str:
    text = _normalize_display_name(platform, display_name)
    if display_name and text != _default_bot_name(platform):
        return text
    try:
        from src.platform.activation_service import list_platform_bot_statuses

        for status in list_platform_bot_statuses():
            if status.get("platform") == platform:
                configured = _normalize_display_name(platform, str(status.get("display_name", "")))
                if configured:
                    return configured
    except Exception:
        pass
    return text


def _normalize_display_name(platform: str, value: str) -> str:
    text = (value or "").strip()
    if not text or _is_damaged_display_name(text):
        return _default_bot_name(platform)
    return text


def _is_damaged_display_name(value: str) -> bool:
    text = (value or "").strip()
    if not text:
        return False
    damage_markers = ("??????????", "�", "锟", "Ã", "Â")
    return any(marker in text for marker in damage_markers)


def _repair_display_names(conn: Any, rows: list[Any]) -> None:
    changed = False
    for row in rows:
        platform = row[0]
        user_id = row[1]
        raw_display_name = row[2] or ""
        normalized = _normalize_display_name(platform, raw_display_name)
        if normalized != raw_display_name:
            conn.execute(
                """
                UPDATE employee_bot_assignments
                SET display_name = ?
                WHERE platform = ? AND user_id = ?
                """,
                (normalized, platform, user_id),
            )
            changed = True
    if changed:
        conn.commit()
