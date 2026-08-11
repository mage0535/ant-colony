"""面向已开通员工的每日工作简报。"""
from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.gateway import provider_outbound
from src.platform import build_capability_context, invoke_capability
from src.store.database import Database

_TZ = ZoneInfo("Asia/Shanghai")


def run_daily_briefs(platform: str = "wecom", now: float | None = None) -> dict[str, Any]:
    """每天每名启用用户最多投递一次；数据失败以中文降级说明呈现。"""
    timestamp = time.time() if now is None else now
    date_key = datetime.fromtimestamp(timestamp, _TZ).strftime("%Y-%m-%d")
    conn = _conn()
    users = conn.execute(
        "SELECT user_id FROM employee_bot_assignments WHERE platform = ? AND status = 'active' ORDER BY user_id",
        (_normalize_platform(platform),),
    ).fetchall()
    notified = skipped = failed = 0
    errors: list[str] = []
    for row in users:
        user_id = str(row["user_id"])
        if _already_delivered(conn, platform, user_id, date_key):
            skipped += 1
            continue
        try:
            text = _build_brief(_normalize_platform(platform), user_id)
            delivered = provider_outbound.send_platform_text(_normalize_platform(platform), user_id, text)
            _record_delivery(conn, platform, user_id, date_key, "sent" if delivered else "failed", text if delivered else "投递通道返回失败")
            if delivered:
                notified += 1
            else:
                failed += 1
        except Exception as exc:
            failed += 1
            errors.append(f"{user_id}:{exc}")
            _record_delivery(conn, platform, user_id, date_key, "failed", str(exc))
    return {"platform": _normalize_platform(platform), "users": len(users), "notified": notified, "skipped": skipped, "failed": failed, "errors": errors[:20]}


def list_daily_brief_deliveries(user_id: str = "", platform: str = "") -> list[dict[str, Any]]:
    rows = _conn().execute(
        "SELECT platform, user_id, date_key, status, detail, created_at FROM daily_brief_deliveries "
        "WHERE (? = '' OR user_id = ?) AND (? = '' OR platform = ?) ORDER BY created_at DESC LIMIT 200",
        (user_id, user_id, _normalize_platform(platform) if platform else "", _normalize_platform(platform) if platform else ""),
    ).fetchall()
    return [dict(row) for row in rows]


def _build_brief(platform: str, user_id: str) -> str:
    context = build_capability_context(user_id=user_id, platform=platform, scope="personal")
    sections: list[tuple[str, str]] = []
    for label, capability, query in (
        ("日程", "calendar.list", "today"),
        ("待办审批", "approval.list", "all"),
        ("邮箱未读统计", "mail.summary", ""),
    ):
        try:
            content = str(invoke_capability(capability, query, context=context, empty_message="") or "").strip()
        except Exception:
            content = ""
        if content:
            sections.append((label, content[:800]))
    try:
        from src.tools.task_tools import query_tasks_tool

        tasks = str(query_tasks_tool({"user_id": user_id, "from": user_id, "platform": platform}) or "").strip()
        if tasks:
            sections.append(("我的任务", tasks[:800]))
    except Exception:
        pass
    try:
        from src.tools.attendance_tool import query_attendance, query_leave_balance

        leave_balance = str(query_leave_balance(user_id) or "").strip()
        if _is_real_personal_data(leave_balance):
            sections.append(("假期余额", leave_balance[:800]))
        attendance = str(query_attendance(user_id, days=1) or "").strip()
        if _contains_attendance_anomaly(attendance):
            sections.append(("考勤提醒", attendance[:800]))
    except Exception:
        pass
    lines = ["【今日工作简报】", "这是根据你当前权限汇总的个人信息；没有数据的栏目不会展示。"]
    if not sections:
        lines.append("今天暂未读取到日程、待办审批、邮件或任务更新。")
    else:
        for label, content in sections:
            lines.append(f"\n【{label}】\n{content}")
    lines.append("\n你可以继续说“查询我的审批状态”“查今天日程”或“查询任务列表”查看详情。")
    return "\n".join(lines)


def _is_real_personal_data(text: str) -> bool:
    if not text:
        return False
    invalid_markers = ("失败", "不存在", "暂无", "未配置", "无权限", "HTTP")
    return not any(marker in text for marker in invalid_markers)


def _contains_attendance_anomaly(text: str) -> bool:
    if not _is_real_personal_data(text):
        return False
    return any(marker in text for marker in ("迟到", "早退", "缺卡", "异常", "旷工"))


def _conn():
    conn = Database.get().connect()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_brief_deliveries (
            platform TEXT NOT NULL,
            user_id TEXT NOT NULL,
            date_key TEXT NOT NULL,
            status TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            PRIMARY KEY (platform, user_id, date_key)
        )
        """
    )
    conn.commit()
    return conn


def _already_delivered(conn: Any, platform: str, user_id: str, date_key: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM daily_brief_deliveries WHERE platform = ? AND user_id = ? AND date_key = ?",
        (_normalize_platform(platform), user_id, date_key),
    ).fetchone())


def _record_delivery(conn: Any, platform: str, user_id: str, date_key: str, status: str, detail: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO daily_brief_deliveries (platform, user_id, date_key, status, detail, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (_normalize_platform(platform), user_id, date_key, status, detail[:4000], time.time()),
    )
    conn.commit()


def _normalize_platform(platform: str) -> str:
    lowered = str(platform or "wecom").strip().lower()
    return {"wecom_bot": "wecom", "wecom_bot_ws": "wecom", "企微": "wecom", "企业微信": "wecom"}.get(lowered, lowered or "wecom")
