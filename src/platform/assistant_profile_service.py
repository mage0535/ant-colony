"""员工专属 AI 助手的名称、角色与首次会话引导。"""
from __future__ import annotations

import re
import sqlite3
import time
from typing import Any

from src.store.database import Database


_ROLE_OPTIONS = (
    ("通用助手", "general", "日常问答、查询、沟通和综合办公协助"),
    ("文档与制度顾问", "document_specialist", "制度起草、文档优化、模板生成和资料总结"),
    ("项目与任务协同助手", "project_coordinator", "任务分解、会议纪要、进度跟踪和协作推进"),
    ("数据与流程分析助手", "data_analyst", "审批、日程、企业应用数据查询和分析"),
)


def _sqlite_with_retry(conn, action, *, attempts: int = 6):
    for attempt in range(attempts):
        try:
            return action()
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt >= attempts - 1:
                raise
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
            time.sleep(0.15 * (attempt + 1))
    raise RuntimeError("sqlite retry exhausted")


def get_or_create_onboarding(*, platform: str, user_id: str, user_name: str = "") -> dict[str, Any]:
    """返回首次会话提示；首次读取时只落库，不替用户指定名字或角色。"""
    conn = _conn()
    normalized_platform = _normalize_platform(platform)
    normalized_user_id = user_id.strip()
    row = _sqlite_with_retry(
        conn,
        lambda: conn.execute(
            "SELECT assistant_name, user_call_name, role_id, onboarding_seen_at FROM assistant_user_profiles WHERE platform = ? AND user_id = ?",
            (normalized_platform, normalized_user_id),
        ).fetchone(),
    )
    if row:
        return {
            "is_first_conversation": False,
            "assistant_name": str(row["assistant_name"] or "企业 AI 助手"),
            "user_call_name": str(row["user_call_name"] or ""),
            "role_id": str(row["role_id"] or "general"),
            "message": "",
        }
    now = time.time()
    def insert_onboarding():
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO assistant_user_profiles
                (platform, user_id, assistant_name, user_call_name, role_id, onboarding_seen_at, created_at, updated_at)
            VALUES (?, ?, '', ?, 'general', ?, ?, ?)
            """,
            (normalized_platform, normalized_user_id, _clean_name(user_name), now, now, now),
        )
        conn.commit()
        return cursor

    cur = _sqlite_with_retry(conn, insert_onboarding)
    if getattr(cur, "rowcount", 1) == 0:
        return get_or_create_onboarding(platform=normalized_platform, user_id=normalized_user_id, user_name=user_name)
    greeting = f"{user_name}，你好！" if user_name else "你好！"
    return {
        "is_first_conversation": True,
        "assistant_name": "企业 AI 助手",
        "user_call_name": _clean_name(user_name),
        "role_id": "general",
        "message": greeting + "\n\n我是你的企业 AI 助手。为了后续更贴合你的工作，请先为我选择一个常用角色，也可以以后随时切换：\n"
        + _role_menu()
        + "\n\n你还可以给我起名，设置一个专属名字。请直接回复，例如：\n“你的名字叫小智，角色选文档与制度顾问”。\n"
        + "如果暂时不选，直接说“使用通用助手”即可。",
    }


def save_assistant_profile(
    *,
    platform: str,
    user_id: str,
    assistant_name: str = "",
    user_call_name: str = "",
    role_id: str = "",
) -> dict[str, Any]:
    conn = _conn()
    normalized_platform = _normalize_platform(platform)
    existing = get_assistant_profile(platform=normalized_platform, user_id=user_id) or {}
    name = _clean_name(assistant_name) or str(existing.get("assistant_name") or "企业 AI 助手")
    call_name = _clean_name(user_call_name) or str(existing.get("user_call_name") or "")
    role = _normalize_role(role_id) or str(existing.get("role_id") or "general")
    now = time.time()
    def upsert_profile() -> None:
        conn.execute(
            """
            INSERT INTO assistant_user_profiles
                (platform, user_id, assistant_name, user_call_name, role_id, onboarding_seen_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(platform, user_id) DO UPDATE SET
                assistant_name = excluded.assistant_name,
                user_call_name = excluded.user_call_name,
                role_id = excluded.role_id,
                onboarding_seen_at = excluded.onboarding_seen_at,
                updated_at = excluded.updated_at
            """,
            (normalized_platform, user_id.strip(), name, call_name, role, now, now, now),
        )
        conn.commit()

    _sqlite_with_retry(conn, upsert_profile)
    return get_assistant_profile(platform=normalized_platform, user_id=user_id) or {}


def get_assistant_profile(*, platform: str, user_id: str) -> dict[str, Any] | None:
    conn = _conn()
    row = _sqlite_with_retry(
        conn,
        lambda: conn.execute(
            "SELECT platform, user_id, assistant_name, user_call_name, role_id, onboarding_seen_at, created_at, updated_at "
            "FROM assistant_user_profiles WHERE platform = ? AND user_id = ?",
            (_normalize_platform(platform), user_id.strip()),
        ).fetchone(),
    )
    if not row:
        return None
    role = _role_by_id(str(row["role_id"] or "general"))
    return {
        "platform": row["platform"],
        "user_id": row["user_id"],
        "assistant_name": str(row["assistant_name"] or "企业 AI 助手"),
        "user_call_name": str(row["user_call_name"] or ""),
        "role_id": role[1],
        "role_name": role[0],
        "role_description": role[2],
        "onboarding_seen_at": row["onboarding_seen_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def build_profile_status_reply(profile: dict[str, Any]) -> str:
    assistant_name = str(profile.get("assistant_name") or "企业 AI 助手")
    user_call_name = str(profile.get("user_call_name") or "").strip() or "未设置"
    role_name = str(profile.get("role_name") or "通用助手")
    role_description = str(profile.get("role_description") or "").strip()
    description_line = f"\n角色说明：{role_description}" if role_description else ""
    return (
        f"我当前在你的个人会话里叫“{assistant_name}”。\n"
        f"我对你的称呼是：{user_call_name}。\n"
        f"当前常用角色是：{role_name}。{description_line}\n\n"
        "说明：企业微信会话顶部显示的应用或机器人名称可能仍是统一名称，这是企业微信前端入口名称；"
        "你的个人助手名字、称呼和角色会在我与你的对话处理方式中生效。"
    )


def build_profile_update_notice(profile: dict[str, Any]) -> str:
    return (
        "你的企业 AI 助手个人档案已更新。\n\n"
        + build_profile_status_reply(profile)
        + "\n\n你可以问我“你叫什么”或“你现在是什么角色”来确认当前设置。"
    )


def delete_assistant_profile(*, platform: str, user_id: str) -> dict[str, Any]:
    normalized_platform = _normalize_platform(platform)
    normalized_user_id = user_id.strip()
    conn = _conn()
    def delete_profile():
        cursor = conn.execute(
            "DELETE FROM assistant_user_profiles WHERE platform = ? AND user_id = ?",
            (normalized_platform, normalized_user_id),
        )
        conn.commit()
        return cursor

    cur = _sqlite_with_retry(conn, delete_profile)
    return {"platform": normalized_platform, "user_id": normalized_user_id, "deleted": cur.rowcount > 0}


def role_options() -> list[dict[str, str]]:
    return [{"name": name, "id": role_id, "description": description} for name, role_id, description in _ROLE_OPTIONS]


def extract_profile_request(text: str) -> dict[str, str] | None:
    """识别明确的命名/角色指令；不从普通聊天中猜测用户意图。"""
    normalized = str(text or "").strip()
    if not normalized:
        return None
    name = ""
    match = re.search(r"(?:你的名字叫|叫你|以后叫你|命名为)\s*[：:：]?\s*([^，。；;！!\n]{1,20})", normalized)
    if match:
        name = _clean_name(match.group(1))
    user_call_name = ""
    call_match = re.search(r"(?:叫我|称呼我|以后叫我|以后称呼我|你可以叫我)\s*[：:：]?\s*([^，。；;！!\n]{1,20})", normalized)
    if call_match:
        user_call_name = _clean_name(call_match.group(1))
    role_id = ""
    for role_name, candidate_id, _ in _ROLE_OPTIONS:
        if role_name in normalized:
            role_id = candidate_id
            break
    if "使用通用助手" in normalized or "通用助手" in normalized and any(word in normalized for word in ("角色", "使用", "选择")):
        role_id = "general"
    return {"assistant_name": name, "user_call_name": user_call_name, "role_id": role_id} if name or user_call_name or role_id else None


def _conn():
    conn = Database.get().connect()

    def ensure_schema() -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS assistant_user_profiles (
                platform TEXT NOT NULL,
                user_id TEXT NOT NULL,
                assistant_name TEXT NOT NULL DEFAULT '',
                user_call_name TEXT NOT NULL DEFAULT '',
                role_id TEXT NOT NULL DEFAULT 'general',
                onboarding_seen_at REAL NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (platform, user_id)
            )
            """
        )
        cols = {row[1] for row in conn.execute("PRAGMA table_info(assistant_user_profiles)").fetchall()}
        if "user_call_name" not in cols:
            conn.execute("ALTER TABLE assistant_user_profiles ADD COLUMN user_call_name TEXT NOT NULL DEFAULT ''")
        conn.commit()

    _sqlite_with_retry(conn, ensure_schema)
    return conn


def _role_menu() -> str:
    return "\n".join(f"{index}. {name}：{description}" for index, (name, _, description) in enumerate(_ROLE_OPTIONS, start=1))


def _role_by_id(role_id: str) -> tuple[str, str, str]:
    for item in _ROLE_OPTIONS:
        if item[1] == role_id:
            return item
    return _ROLE_OPTIONS[0]


def _normalize_role(value: str) -> str:
    text = str(value or "").strip()
    if any(item[1] == text for item in _ROLE_OPTIONS):
        return text
    for name, role_id, _ in _ROLE_OPTIONS:
        if name == text:
            return role_id
    return ""


def _clean_name(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text or len(text) > 20 or any(char in text for char in "<>[]{}\\/"):
        return ""
    return text


def _normalize_platform(platform: str) -> str:
    lowered = str(platform or "wecom").strip().lower()
    return {"wecom_bot": "wecom", "wecom_bot_ws": "wecom", "企微": "wecom", "企业微信": "wecom"}.get(lowered, lowered or "wecom")
