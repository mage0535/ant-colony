from __future__ import annotations

import email
import hashlib
import html
import imaplib
import logging
import os
import poplib
import re
import time
from email.header import decode_header
from email.utils import parsedate_to_datetime
from typing import Any

from src.store.database import Database

logger = logging.getLogger(__name__)
_MAIL_LLM_PROFILE_FAILURES: dict[str, float] = {}
_MAIL_LLM_FAILURE_TTL_SECONDS = 600.0


_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS mail_accounts (
    account_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    user_id TEXT NOT NULL,
    account_label TEXT NOT NULL DEFAULT '',
    email_address TEXT NOT NULL DEFAULT '',
    protocol TEXT NOT NULL DEFAULT 'imap',
    imap_host TEXT NOT NULL DEFAULT '',
    imap_port INTEGER NOT NULL DEFAULT 993,
    imap_ssl INTEGER NOT NULL DEFAULT 1,
    encryption TEXT NOT NULL DEFAULT '',
    username TEXT NOT NULL DEFAULT '',
    password TEXT NOT NULL DEFAULT '',
    folder TEXT NOT NULL DEFAULT 'INBOX',
    poll_interval_minutes INTEGER NOT NULL DEFAULT 1,
    enabled INTEGER NOT NULL DEFAULT 1,
    updated_by TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL DEFAULT (cast(strftime('%s','now') as real)),
    PRIMARY KEY (account_id)
)
"""

_NOTIFICATION_STATE_SQL = """
CREATE TABLE IF NOT EXISTS mail_notification_state (
    account_id TEXT PRIMARY KEY,
    last_polled_at REAL NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
)
"""

_NOTIFICATION_EVENT_SQL = """
CREATE TABLE IF NOT EXISTS mail_notification_events (
    account_id TEXT NOT NULL,
    message_key TEXT NOT NULL,
    platform TEXT NOT NULL,
    user_id TEXT NOT NULL,
    source_label TEXT NOT NULL DEFAULT '',
    subject TEXT NOT NULL DEFAULT '',
    sender TEXT NOT NULL DEFAULT '',
    received_at TEXT NOT NULL DEFAULT '',
    received_at_ts REAL NOT NULL DEFAULT 0,
    delivery_status TEXT NOT NULL DEFAULT '',
    delivery_error TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (account_id, message_key)
)
"""


def _conn():
    db = Database.get()
    conn = db.connect()
    _ensure_mail_accounts_schema(conn)
    _ensure_mail_notification_schema(conn)
    return conn


def _ensure_mail_accounts_schema(conn) -> None:
    table = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='mail_accounts'").fetchone()
    if not table:
        conn.execute(_TABLE_SQL)
        conn.commit()
        return
    cols = {_pragma_column_name(row) for row in conn.execute("PRAGMA table_info(mail_accounts)").fetchall()}
    cols.discard("")
    if "account_id" not in cols:
        conn.execute("ALTER TABLE mail_accounts RENAME TO mail_accounts_legacy")
        conn.execute(_TABLE_SQL)
        legacy_rows = conn.execute("SELECT * FROM mail_accounts_legacy").fetchall()
        for row in legacy_rows:
            data = dict(row)
            platform = _clean(data.get("platform") or "wecom")
            user_id = _clean(data.get("user_id"))
            email_address = _clean(data.get("email_address"))
            account_id = _mail_account_id(platform, user_id, email_address)
            conn.execute(
                """
                INSERT OR REPLACE INTO mail_accounts (
                    account_id,platform,user_id,account_label,email_address,imap_host,imap_port,imap_ssl,encryption,username,password,folder,
                    poll_interval_minutes,enabled,updated_by,updated_at,protocol
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    account_id,
                    platform,
                    user_id,
                    "",
                    email_address,
                    data.get("imap_host", ""),
                    int(data.get("imap_port") or 993),
                    int(data.get("imap_ssl") or 0),
                    data.get("encryption", ""),
                    data.get("username", ""),
                    data.get("password", ""),
                    data.get("folder", "INBOX"),
                    int(data.get("poll_interval_minutes") or 1),
                    int(data.get("enabled") or 0),
                    data.get("updated_by", ""),
                    float(data.get("updated_at") or time.time()),
                    data.get("protocol", "imap"),
                ),
            )
        conn.execute("DROP TABLE mail_accounts_legacy")
        conn.commit()
        return
    if "protocol" not in cols:
        conn.execute("ALTER TABLE mail_accounts ADD COLUMN protocol TEXT NOT NULL DEFAULT 'imap'")
    if "encryption" not in cols:
        conn.execute("ALTER TABLE mail_accounts ADD COLUMN encryption TEXT NOT NULL DEFAULT ''")
    if "account_label" not in cols:
        conn.execute("ALTER TABLE mail_accounts ADD COLUMN account_label TEXT NOT NULL DEFAULT ''")
    conn.execute("UPDATE mail_accounts SET account_label='默认邮箱' WHERE account_label IS NULL OR trim(account_label)=''")
    conn.commit()

def _pragma_column_name(row: Any) -> str:
    """Return a PRAGMA table_info column name under any active row_factory."""
    if isinstance(row, dict):
        return str(row.get("name") or "")
    try:
        return str(row["name"] or "")
    except (IndexError, KeyError, TypeError):
        try:
            return str(row[1] or "")
        except (IndexError, KeyError, TypeError):
            return ""


def _ensure_mail_notification_schema(conn) -> None:
    conn.execute(_NOTIFICATION_STATE_SQL)
    conn.execute(_NOTIFICATION_EVENT_SQL)
    conn.commit()


def save_mail_account(payload: dict[str, Any], *, updated_by: str = "") -> dict[str, Any]:
    platform = _clean(payload.get("platform") or "wecom")
    user_id = _clean(payload.get("user_id"))
    if not user_id:
        raise ValueError("缺少员工用户 ID")
    inferred = infer_mail_account_defaults(
        platform=platform,
        user_id=user_id,
        email_address=_clean(payload.get("email_address")),
    )
    merged = {**inferred, **{k: v for k, v in payload.items() if v not in (None, "")}}
    email_address = _clean(merged.get("email_address"))
    imap_host = _clean(merged.get("imap_host"))
    username = _clean(merged.get("username") or email_address)
    password = str(payload.get("password") or "")
    if not email_address or not imap_host or not username:
        raise ValueError("未能自动识别该员工邮箱地址或服务器地址；请先同步企业 IM 通讯录邮箱，或手工填写邮箱地址和服务器地址")

    requested_account_id = _clean(merged.get("account_id"))
    account_id = requested_account_id or _mail_account_id(platform, user_id, email_address)
    existing = get_mail_account_by_id(account_id, include_secret=True)
    replace_existing = bool(payload.get("replace_existing", False))
    if (
        existing
        and requested_account_id
        and _clean(existing.get("email_address")).lower() != email_address.lower()
        and not replace_existing
    ):
        # Admin UI can keep the hidden account_id after editing an existing
        # account. If the address changes, treat it as a new mailbox by default
        # so adding a second mailbox cannot overwrite the first one accidentally.
        account_id = _mail_account_id(platform, user_id, email_address)
        existing = get_mail_account_by_id(account_id, include_secret=True)
    if existing is None and not requested_account_id:
        existing = get_mail_account(platform, user_id, include_secret=True)
        if existing and _clean(existing.get("email_address")).lower() != email_address.lower():
            existing = None
    if not password and existing:
        password = str(existing.get("password") or "")

    protocol = _normalize_protocol(merged.get("protocol") or "imap")
    encryption = _normalize_encryption(merged.get("encryption"), legacy_ssl=merged.get("imap_ssl"))

    conn = _conn()
    conn.execute(
        """
        INSERT INTO mail_accounts (
            account_id,platform,user_id,account_label,email_address,imap_host,imap_port,imap_ssl,encryption,username,password,folder,
            poll_interval_minutes,enabled,updated_by,updated_at,protocol
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(account_id) DO UPDATE SET
            email_address=excluded.email_address,
            account_label=excluded.account_label,
            imap_host=excluded.imap_host,
            imap_port=excluded.imap_port,
            imap_ssl=excluded.imap_ssl,
            encryption=excluded.encryption,
            username=excluded.username,
            password=excluded.password,
            folder=excluded.folder,
            poll_interval_minutes=excluded.poll_interval_minutes,
            enabled=excluded.enabled,
            updated_by=excluded.updated_by,
            updated_at=excluded.updated_at,
            protocol=excluded.protocol
        """,
        (
            account_id,
            platform,
            user_id,
            _clean(merged.get("account_label")) or "默认邮箱",
            email_address,
            imap_host,
            int(merged.get("imap_port") or _default_mail_port(protocol, encryption)),
            1 if encryption == "ssl_tls" else 0,
            encryption,
            username,
            password,
            _clean(merged.get("folder") or "INBOX"),
            max(1, int(merged.get("poll_interval_minutes") or 1)),
            1 if bool(merged.get("enabled", True)) else 0,
            updated_by,
            time.time(),
            protocol,
        ),
    )
    conn.commit()
    return _public_account(get_mail_account_by_id(account_id, include_secret=True) or {})


def list_mail_accounts(*, platform: str = "", user_id: str = "") -> dict[str, Any]:
    conn = _conn()
    where: list[str] = []
    params: list[Any] = []
    if platform:
        where.append("platform=?")
        params.append(platform)
    if user_id:
        where.append("m.user_id=?")
        params.append(user_id)
    if platform:
        # Rewrite the first condition after building params so the same user
        # filters can be reused while joining org_users for display names.
        where[0] = "m.platform=?"
    sql = (
        "SELECT m.*, COALESCE(u.name, '') AS user_name "
        "FROM mail_accounts m "
        "LEFT JOIN org_users u ON u.platform=m.platform AND u.user_id=m.user_id"
        + ((" WHERE " + " AND ".join(where)) if where else "")
        + " ORDER BY m.platform,m.user_id,m.updated_at,m.email_address"
    )
    return {"accounts": [_public_account(dict(row)) for row in conn.execute(sql, params).fetchall()]}


def infer_mail_account_defaults(
    *,
    platform: str = "wecom",
    user_id: str = "",
    email_address: str = "",
) -> dict[str, Any]:
    """Infer mailbox connection fields from org email and existing same-domain accounts."""
    normalized_platform = _clean(platform or "wecom")
    normalized_user_id = _clean(user_id)
    conn = _conn()
    org_email = ""
    org_name = ""
    if normalized_user_id:
        row = conn.execute(
            "SELECT name,email FROM org_users WHERE platform=? AND user_id=?",
            (normalized_platform, normalized_user_id),
        ).fetchone()
        if row:
            org_name = str(row["name"] or "")
            org_email = str(row["email"] or "")

    address = _clean(email_address) or _clean(org_email)
    domain = address.split("@", 1)[1].lower() if "@" in address else ""
    template = None
    if domain:
        template = conn.execute(
            """
            SELECT *
            FROM mail_accounts
            WHERE platform=? AND lower(email_address) LIKE ?
              AND trim(imap_host) != ''
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (normalized_platform, f"%@{domain}"),
        ).fetchone()

    if template:
        data = dict(template)
        encryption = _account_encryption(data)
        source = f"已按同域邮箱 {domain} 复用现有服务器配置"
        return {
            "platform": normalized_platform,
            "user_id": normalized_user_id,
            "user_name": org_name,
            "email_address": address,
            "account_label": "默认邮箱",
            "protocol": _normalize_protocol(data.get("protocol") or "imap"),
            "imap_host": data.get("imap_host", ""),
            "imap_port": int(data.get("imap_port") or _default_mail_port(_normalize_protocol(data.get("protocol")), encryption)),
            "encryption": encryption,
            "imap_ssl": encryption == "ssl_tls",
            "username": address,
            "folder": data.get("folder", "INBOX") or "INBOX",
            "poll_interval_minutes": 1,
            "enabled": True,
            "source": source,
        }

    protocol = "imap"
    encryption = "ssl_tls"
    host = f"imap.{domain}" if domain else ""
    return {
        "platform": normalized_platform,
        "user_id": normalized_user_id,
        "user_name": org_name,
        "email_address": address,
        "account_label": "默认邮箱",
        "protocol": protocol,
        "imap_host": host,
        "imap_port": _default_mail_port(protocol, encryption),
        "encryption": encryption,
        "imap_ssl": True,
        "username": address,
        "folder": "INBOX",
        "poll_interval_minutes": 1,
        "enabled": True,
        "source": "未找到同域已配置邮箱，已按通用 IMAP/SSL 模板生成；保存后必须真实测试",
    }


def get_mail_account(platform: str, user_id: str, *, include_secret: bool = False) -> dict[str, Any] | None:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM mail_accounts WHERE platform=? AND user_id=? ORDER BY enabled DESC,email_address LIMIT 1",
        (_clean(platform or "wecom"), _clean(user_id)),
    ).fetchone()
    if not row:
        return None
    data = dict(row)
    return data if include_secret else _public_account(data)


def get_mail_account_by_id(account_id: str, *, include_secret: bool = False) -> dict[str, Any] | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM mail_accounts WHERE account_id=?", (_clean(account_id),)).fetchone()
    if not row:
        return None
    data = dict(row)
    return data if include_secret else _public_account(data)


def set_mail_account_status(platform: str, user_id: str, *, enabled: bool, updated_by: str = "", account_id: str = "") -> dict[str, Any]:
    conn = _conn()
    if account_id:
        conn.execute(
            "UPDATE mail_accounts SET enabled=?, updated_by=?, updated_at=? WHERE account_id=?",
            (1 if enabled else 0, updated_by, time.time(), _clean(account_id)),
        )
    else:
        conn.execute(
            "UPDATE mail_accounts SET enabled=?, updated_by=?, updated_at=? WHERE platform=? AND user_id=?",
            (1 if enabled else 0, updated_by, time.time(), _clean(platform or "wecom"), _clean(user_id)),
        )
    conn.commit()
    account = get_mail_account_by_id(account_id, include_secret=True) if account_id else get_mail_account(platform, user_id, include_secret=True)
    if not account:
        raise ValueError("未找到邮箱配置")
    return _public_account(account)


def delete_mail_account(platform: str, user_id: str, *, account_id: str = "") -> dict[str, Any]:
    conn = _conn()
    if account_id:
        cur = conn.execute("DELETE FROM mail_accounts WHERE account_id=?", (_clean(account_id),))
    else:
        cur = conn.execute(
            "DELETE FROM mail_accounts WHERE platform=? AND user_id=?",
            (_clean(platform or "wecom"), _clean(user_id)),
        )
    conn.commit()
    return {"deleted": cur.rowcount > 0, "platform": platform, "user_id": user_id, "account_id": account_id}


def summarize_user_mailbox(platform: str, user_id: str, *, query: str = "", limit: int = 10) -> str:
    accounts = list_mail_accounts(platform=platform or "wecom", user_id=user_id).get("accounts", [])
    secret_accounts = [get_mail_account_by_id(str(account.get("account_id") or ""), include_secret=True) for account in accounts]
    secret_accounts = [account for account in secret_accounts if account]
    if not secret_accounts:
        return (
            "当前企业 IM 账号尚未配置邮箱摘要。请管理员在后台“邮箱配置”中为当前员工保存邮件接收协议、"
            "服务器、账号和授权码；其他员工的邮箱配置不会共享给本账号。"
        )
    enabled_accounts = [account for account in secret_accounts if int(account.get("enabled") or 0)]
    if not enabled_accounts:
        return "该员工邮箱摘要功能已停用，请管理员在后台启用后再使用。"
    blocks: list[str] = []
    for account in enabled_accounts:
        body = _summarize_account_mailbox(account, query=query, limit=limit)
        blocks.append(_with_source_context(account, body))
    return "\n\n".join(blocks)


def summarize_mail_account(account_id: str, *, query: str = "", limit: int = 10) -> str:
    account = get_mail_account_by_id(account_id, include_secret=True)
    if not account:
        return "未找到邮箱配置。"
    if not int(account.get("enabled") or 0):
        return "该邮箱摘要功能已停用，请管理员在后台启用后再使用。"
    body = _summarize_account_mailbox(account, query=query, limit=limit)
    return _with_source_context(account, body)


def run_mail_new_message_notifier(platform: str = "wecom", *, force: bool = False, limit: int = 30) -> dict[str, Any]:
    """Poll enabled mailboxes and push only newly seen messages to active assistants."""
    lock_path = _acquire_mail_notifier_lock()
    if not lock_path:
        return {
            "platform": _clean(platform or "wecom"),
            "checked_accounts": 0,
            "skipped_locked": 1,
            "new_messages": 0,
            "sent": 0,
            "baselined": 0,
            "no_active_ai_assistant": 0,
            "failed": 0,
            "errors": [],
            "message": "上一轮邮箱监听仍在运行，本轮已跳过，避免并发重复扫描。",
        }
    try:
        return _run_mail_new_message_notifier_unlocked(platform=platform, force=force, limit=limit)
    finally:
        _release_mail_notifier_lock(lock_path)


def _run_mail_new_message_notifier_unlocked(platform: str = "wecom", *, force: bool = False, limit: int = 30) -> dict[str, Any]:
    normalized_platform = _clean(platform or "wecom")
    conn = _conn()
    accounts = [
        get_mail_account_by_id(str(account.get("account_id") or ""), include_secret=True)
        for account in list_mail_accounts(platform=normalized_platform).get("accounts", [])
    ]
    accounts = [account for account in accounts if account and int(account.get("enabled") or 0)]
    now = time.time()
    stats = {
        "platform": normalized_platform,
        "checked_accounts": 0,
        "skipped_interval": 0,
        "new_messages": 0,
        "sent": 0,
        "baselined": 0,
        "no_active_ai_assistant": 0,
        "failed": 0,
        "errors": [],
    }
    for account in accounts:
        account_id = str(account.get("account_id") or "")
        if not account_id:
            continue
        state = _mail_notification_state(conn, account_id)
        interval_seconds = max(60, int(account.get("poll_interval_minutes") or 1) * 60)
        if state and not force and now - float(state["last_polled_at"] or 0) < interval_seconds:
            stats["skipped_interval"] += 1
            continue

        try:
            items = _fetch_recent_mail_items(account, limit=limit)
        except Exception as exc:
            error = _mail_connection_error(_normalize_protocol(account.get("protocol") or "imap").upper(), _account_encryption(account), exc)
            _upsert_mail_notification_state(conn, account_id, now, error)
            stats["errors"].append({"account_id": account_id, "error": error})
            continue

        stats["checked_accounts"] += 1
        is_first_poll = state is None
        first_run_lookback = _first_run_notify_seconds()
        for item in sorted(items, key=lambda entry: float(entry.get("received_at_ts") or 0)):
            message_key = str(item.get("message_key") or "")
            if not message_key or _mail_notification_event_exists(conn, account_id, message_key):
                continue
            should_notify = not is_first_poll
            received_at_ts = float(item.get("received_at_ts") or 0)
            if is_first_poll and first_run_lookback > 0 and received_at_ts and now - received_at_ts <= first_run_lookback:
                should_notify = True

            if not should_notify:
                _record_mail_notification_event(conn, account, item, "baseline", "首次扫描基线，不推送历史邮件")
                stats["baselined"] += 1
                continue

            stats["new_messages"] += 1
            if not _assistant_allows_notification(normalized_platform, str(account.get("user_id") or "")):
                _record_mail_notification_event(conn, account, item, "no_active_ai_assistant", "员工 AI 助手未开通或未启用")
                stats["no_active_ai_assistant"] += 1
                continue

            hydrated_item = _hydrate_mail_item_for_notification(account, item)
            ok = _send_mail_notification(account, hydrated_item)
            _record_mail_notification_event(
                conn,
                account,
                hydrated_item,
                "sent" if ok else "send_failed",
                "" if ok else "消息通道返回失败，将在下一轮后续检测中保留记录",
            )
            stats["sent" if ok else "failed"] += 1
        _upsert_mail_notification_state(conn, account_id, now, "")
    conn.commit()
    return stats


def diagnose_mail_account_connection(account_id: str) -> str:
    account = get_mail_account_by_id(account_id, include_secret=True)
    if not account:
        return "未找到邮箱配置，无法诊断。"
    password = str(account.get("password") or "")
    if not password:
        return "该邮箱未保存密码或客户端授权码，无法进行真实登录诊断。"

    attempts = _mail_diagnostic_attempts(account)
    current_key = (
        _normalize_protocol(account.get("protocol") or "imap"),
        str(account.get("imap_host") or "").strip(),
        int(account.get("imap_port") or 0),
        _account_encryption(account),
        str(account.get("username") or account.get("email_address") or "").strip(),
    )
    outcomes: list[dict[str, str]] = []
    for attempt in attempts:
        outcome = _probe_mail_login(
            protocol=attempt["protocol"],
            host=attempt["host"],
            port=int(attempt["port"]),
            encryption=attempt["encryption"],
            username=attempt["username"],
            password=password,
        )
        outcomes.append({**attempt, **outcome})
        if outcome["ok"] == "true":
            attempt_key = (
                attempt["protocol"],
                attempt["host"],
                int(attempt["port"]),
                attempt["encryption"],
                attempt["username"],
            )
            if attempt_key == current_key:
                return (
                    "诊断结果：当前后台保存的邮箱配置和密码/授权码已经可以通过客户端协议登录。\n"
                    "如果页面之前仍提示登录失败，通常是旧密码尚未重新保存、测试结果来自旧缓存，或保存后未重新点击该邮箱的“测试”。"
                    "请刷新管理员后台后，对这一个邮箱重新点击“测试”。"
                )
            return (
                "诊断结果：当前保存的密码/授权码可用，但后台配置的协议、服务器、端口、加密方式或账号写法不匹配。\n"
                f"建议配置为：{attempt['protocol'].upper()}，服务器 {attempt['host']}，端口 {attempt['port']}，"
                f"加密方式 {_display_encryption(attempt['encryption'])}，账号 {attempt['username']}。"
            )

    full_email_results = [item for item in outcomes if "@" in item["username"]]
    local_part_results = [item for item in outcomes if "@" not in item["username"]]
    full_email_auth_failed = bool(full_email_results) and all(_is_auth_error(item.get("error", "")) for item in full_email_results)
    local_part_illegal = bool(local_part_results) and all(_is_illegal_email_error(item.get("error", "")) for item in local_part_results)
    if full_email_auth_failed and local_part_illegal:
        return (
            "诊断结果：已用当前保存的密码/授权码测试该服务商常见 POP3/IMAP 组合，完整邮箱账号均被服务端拒绝；"
            "邮箱前缀账号被服务端判定为非法账号。\n"
            "结论：账号写法应使用完整邮箱地址；网页端密码正确不等于 POP3/IMAP 客户端协议可登录，"
            "当前服务端拒绝的是客户端协议登录。\n"
            "处理方法：请在邮箱后台为该邮箱开启 POP3/IMAP/SMTP 客户端登录；如果企业邮箱要求客户端授权密码，"
            "请生成客户端授权密码后在管理员后台重新保存并测试。"
        )

    auth_failed = [item for item in outcomes if _is_auth_error(item.get("error", ""))]
    if auth_failed:
        return (
            "诊断结果：服务商已响应登录请求，但拒绝当前保存的密码/授权码。\n"
            "说明：网页端密码正确仍可能被 POP3/IMAP 客户端协议拒绝。\n"
            "处理方法：请优先确认该邮箱已开启 POP3/IMAP 客户端登录；如果企业邮箱要求客户端授权密码，请生成后重新保存。"
        )

    wrong_tls = [item for item in outcomes if "WRONG_VERSION_NUMBER" in str(item.get("error", "")).upper()]
    if wrong_tls:
        return (
            "诊断结果：至少一个连接方式被服务器拒绝 SSL/TLS 握手。\n"
            "处理方法：请按邮箱服务商文档核对端口和加密方式，例如 110 通常不加密，995 通常为 SSL/TLS。"
        )

    details = "; ".join(
        f"{item['protocol'].upper()} {item['host']}:{item['port']} {_display_encryption(item['encryption'])} {item['username']} -> {item.get('error', '')}"
        for item in outcomes[:6]
    )
    return f"诊断结果：未找到可登录组合。最近诊断结果：{details}"


def _summarize_account_mailbox(account: dict[str, Any], *, query: str = "", limit: int = 10) -> str:
    password = str(account.get("password") or "")
    if not password:
        return "该员工邮箱授权码/密码尚未配置，请管理员在后台补充后再使用。"

    host = str(account.get("imap_host") or "")
    port = int(account.get("imap_port") or 993)
    protocol = _normalize_protocol(account.get("protocol") or "imap")
    username = str(account.get("username") or account.get("email_address") or "")
    folder = str(account.get("folder") or "INBOX")
    if protocol == "pop3":
        return _summarize_pop3(account, query=query, limit=limit)
    if protocol == "exchange":
        return _summarize_exchange_ews(account, query=query, limit=limit)
    if protocol != "imap":
        return f"暂不支持的邮箱协议：{protocol}"
    try:
        encryption = _account_encryption(account)
        client = imaplib.IMAP4_SSL(host, port) if encryption == "ssl_tls" else imaplib.IMAP4(host, port)
        try:
            if encryption == "starttls":
                client.starttls()
            client.login(username, password)
            client.select(folder)
            criteria = _imap_search_criteria(query)
            _, data = client.search(None, *criteria)
            uids = data[0].split() if data and data[0] else []
            if not uids:
                return f"未找到匹配邮件：{query}" if query else "当前收件箱没有邮件。"
            lines = []
            for uid in uids[-max(1, min(int(limit or 10), 30)):]:
                _, msg_data = client.uid("fetch", uid, "(RFC822)")
                raw = _extract_raw_message(msg_data)
                if not raw:
                    continue
                lines.append(_format_mail_summary(email.message_from_bytes(raw), account=account))
            return "\n\n".join(lines) if lines else "未读取到可展示的邮件内容。"
        finally:
            try:
                client.logout()
            except Exception:
                pass
    except Exception as exc:
        return _mail_connection_error("IMAP", _account_encryption(account), exc)


def _fetch_recent_mail_items(account: dict[str, Any], *, limit: int = 30) -> list[dict[str, Any]]:
    protocol = _normalize_protocol(account.get("protocol") or "imap")
    if protocol == "pop3":
        return _fetch_recent_pop3_items(account, limit=limit)
    if protocol == "exchange":
        return _fetch_recent_exchange_items(account, limit=limit)
    if protocol != "imap":
        raise ValueError(f"暂不支持的邮箱协议：{protocol}")
    host = str(account.get("imap_host") or "")
    port = int(account.get("imap_port") or 993)
    username = str(account.get("username") or account.get("email_address") or "")
    password = str(account.get("password") or "")
    folder = str(account.get("folder") or "INBOX")
    encryption = _account_encryption(account)
    client = imaplib.IMAP4_SSL(host, port) if encryption == "ssl_tls" else imaplib.IMAP4(host, port)
    try:
        if encryption == "starttls":
            client.starttls()
        client.login(username, password)
        client.select(folder)
        _, data = client.search(None, "ALL")
        uids = data[0].split() if data and data[0] else []
        items: list[dict[str, Any]] = []
        for uid in uids[-max(1, min(int(limit or 30), 100)):]:
            _, msg_data = client.uid("fetch", uid, "(RFC822)")
            raw = _extract_raw_message(msg_data)
            if not raw:
                continue
            msg = email.message_from_bytes(raw)
            fallback = f"imap:{uid.decode(errors='ignore') if isinstance(uid, bytes) else uid}"
            items.append(_mail_item_from_message(msg, account=account, fallback_key=fallback, raw=raw, include_summary=False))
        return items
    finally:
        try:
            client.logout()
        except Exception:
            pass


def _summarize_pop3(account: dict[str, Any], *, query: str = "", limit: int = 10) -> str:
    host = str(account.get("imap_host") or "")
    port = int(account.get("imap_port") or 995)
    username = str(account.get("username") or account.get("email_address") or "")
    password = str(account.get("password") or "")
    encryption = _account_encryption(account)
    try:
        client = poplib.POP3_SSL(host, port, timeout=20) if encryption == "ssl_tls" else poplib.POP3(host, port, timeout=20)
        try:
            if encryption == "starttls":
                client.stls()
            client.user(username)
            client.pass_(password)
            _, listings, _ = client.list()
            if not listings:
                return "当前 POP3 邮箱没有邮件。"
            messages: list[email.message.Message] = []
            for listing in listings[-max(1, min(int(limit or 10), 30)):]:
                number = str(listing.split()[0].decode() if isinstance(listing, bytes) else str(listing).split()[0])
                _, lines, _ = client.retr(int(number))
                raw = b"\n".join(line if isinstance(line, bytes) else str(line).encode("utf-8") for line in lines)
                msg = email.message_from_bytes(raw)
                if _matches_query(msg, query):
                    messages.append(msg)
            if not messages:
                return f"未找到匹配邮件：{query}" if query else "未读取到可展示的邮件内容。"
            return "\n\n".join(_format_mail_summary(msg, account=account) for msg in messages)
        finally:
            try:
                client.quit()
            except Exception:
                pass
    except Exception as exc:
        return _mail_connection_error("POP3", encryption, exc)


def _fetch_recent_pop3_items(account: dict[str, Any], *, limit: int = 30) -> list[dict[str, Any]]:
    host = str(account.get("imap_host") or "")
    port = int(account.get("imap_port") or 995)
    username = str(account.get("username") or account.get("email_address") or "")
    password = str(account.get("password") or "")
    encryption = _account_encryption(account)
    client = poplib.POP3_SSL(host, port, timeout=20) if encryption == "ssl_tls" else poplib.POP3(host, port, timeout=20)
    try:
        if encryption == "starttls":
            client.stls()
        client.user(username)
        client.pass_(password)
        _, listings, _ = client.list()
        uid_map = _pop3_uid_map(client)
        items: list[dict[str, Any]] = []
        for listing in listings[-max(1, min(int(limit or 30), 100)):]:
            number = str(listing.split()[0].decode() if isinstance(listing, bytes) else str(listing).split()[0])
            uid = uid_map.get(number, "")
            msg = _pop3_header_message(client, number)
            item = _mail_item_from_message(
                msg,
                account=account,
                fallback_key=f"pop3:{uid or number}",
                raw=None,
                include_summary=False,
            )
            item["_pop3_number"] = number
            item["_pop3_uid"] = uid
            items.append(item)
        return items
    finally:
        try:
            client.quit()
        except Exception:
            pass


def _pop3_uid_map(client: Any) -> dict[str, str]:
    try:
        _, rows, _ = client.uidl()
    except Exception:
        return {}
    result: dict[str, str] = {}
    for row in rows or []:
        text = row.decode(errors="ignore") if isinstance(row, bytes) else str(row)
        parts = text.strip().split(maxsplit=1)
        if len(parts) == 2:
            result[parts[0]] = parts[1]
    return result


def _pop3_header_message(client: Any, number: str) -> email.message.Message:
    try:
        _, lines, _ = client.top(int(number), 0)
        raw = b"\n".join(line if isinstance(line, bytes) else str(line).encode("utf-8") for line in lines)
        if raw:
            return email.message_from_bytes(raw)
    except Exception:
        pass
    msg = email.message.EmailMessage()
    msg["Subject"] = "(无标题)"
    msg["From"] = "(未知发件人)"
    msg["Date"] = "(无时间)"
    return msg


def _mail_diagnostic_attempts(account: dict[str, Any]) -> list[dict[str, Any]]:
    host = str(account.get("imap_host") or "").strip()
    port = int(account.get("imap_port") or 0)
    protocol = _normalize_protocol(account.get("protocol") or "imap")
    encryption = _account_encryption(account)
    email_address = str(account.get("email_address") or "").strip()
    username = str(account.get("username") or email_address).strip()
    usernames = [name for name in [username, email_address, email_address.split("@", 1)[0] if "@" in email_address else ""] if name]

    candidates: list[dict[str, Any]] = []
    if host and port:
        candidates.append({"protocol": protocol, "host": host, "port": port, "encryption": encryption})
    if "qiye.163.com" in host.lower():
        candidates.extend(
            [
                {"protocol": "pop3", "host": "pophz.qiye.163.com", "port": 110, "encryption": "none"},
                {"protocol": "pop3", "host": "pophz.qiye.163.com", "port": 995, "encryption": "ssl_tls"},
                {"protocol": "pop3", "host": "pop.qiye.163.com", "port": 110, "encryption": "none"},
                {"protocol": "pop3", "host": "pop.qiye.163.com", "port": 995, "encryption": "ssl_tls"},
                {"protocol": "imap", "host": "imaphz.qiye.163.com", "port": 143, "encryption": "none"},
                {"protocol": "imap", "host": "imaphz.qiye.163.com", "port": 993, "encryption": "ssl_tls"},
                {"protocol": "imap", "host": "imap.qiye.163.com", "port": 143, "encryption": "none"},
                {"protocol": "imap", "host": "imap.qiye.163.com", "port": 993, "encryption": "ssl_tls"},
            ]
        )

    attempts: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int, str, str]] = set()
    for candidate in candidates:
        for candidate_username in usernames:
            key = (
                str(candidate["protocol"]),
                str(candidate["host"]),
                int(candidate["port"]),
                str(candidate["encryption"]),
                candidate_username,
            )
            if key in seen:
                continue
            seen.add(key)
            attempts.append(
                {
                    "protocol": key[0],
                    "host": key[1],
                    "port": key[2],
                    "encryption": key[3],
                    "username": key[4],
                }
            )
    return attempts[:24]


def _probe_mail_login(*, protocol: str, host: str, port: int, encryption: str, username: str, password: str) -> dict[str, str]:
    try:
        if protocol == "pop3":
            client = poplib.POP3_SSL(host, port, timeout=8) if encryption == "ssl_tls" else poplib.POP3(host, port, timeout=8)
            try:
                if encryption == "starttls":
                    client.stls()
                client.user(username)
                client.pass_(password)
                return {"ok": "true", "error": ""}
            finally:
                try:
                    client.quit()
                except Exception:
                    pass
        if protocol == "imap":
            client = imaplib.IMAP4_SSL(host, port, timeout=8) if encryption == "ssl_tls" else imaplib.IMAP4(host, port, timeout=8)
            try:
                if encryption == "starttls":
                    client.starttls()
                client.login(username, password)
                return {"ok": "true", "error": ""}
            finally:
                try:
                    client.logout()
                except Exception:
                    pass
        return {"ok": "false", "error": f"暂不支持诊断协议：{protocol}"}
    except Exception as exc:
        return {"ok": "false", "error": str(exc)}


def _is_auth_error(detail: str) -> bool:
    upper_detail = str(detail or "").upper()
    return "LOGIN.PASSERR" in upper_detail or ("AUTH" in upper_detail and "FAIL" in upper_detail) or "PASSWORD" in upper_detail


def _is_illegal_email_error(detail: str) -> bool:
    upper_detail = str(detail or "").upper()
    return "ILLEGAL.EMAIL" in upper_detail or "ILLEGAL EMAIL" in upper_detail


def _display_encryption(encryption: str) -> str:
    return {"ssl_tls": "SSL/TLS", "starttls": "STARTTLS", "none": "不加密"}.get(encryption, encryption or "默认")


def _summarize_exchange_ews(account: dict[str, Any], *, query: str = "", limit: int = 10) -> str:
    try:
        from exchangelib import Account, Configuration, Credentials, DELEGATE  # type: ignore
    except Exception:
        return (
            "Exchange 邮箱需要安装可选依赖 exchangelib 后才能通过 EWS 读取。"
            "本页面已保存账号归属；如果使用 Microsoft 365 Graph，还需要后续配置 Graph OAuth 应用授权。"
        )

    server = str(account.get("imap_host") or "")
    username = str(account.get("username") or account.get("email_address") or "")
    password = str(account.get("password") or "")
    email_address = str(account.get("email_address") or username)
    try:
        credentials = Credentials(username=username, password=password)
        config = Configuration(server=server, credentials=credentials) if server else None
        mailbox = Account(
            primary_smtp_address=email_address,
            config=config,
            credentials=credentials if config is None else None,
            autodiscover=config is None,
            access_type=DELEGATE,
        )
        items = mailbox.inbox.all().order_by("-datetime_received")[: max(1, min(int(limit or 10), 30))]
        lines = []
        for item in items:
            subject = str(getattr(item, "subject", "") or "(无标题)")
            sender_obj = getattr(item, "sender", None)
            sender = str(getattr(sender_obj, "email_address", "") or getattr(sender_obj, "name", "") or "(未知发件人)")
            body = str(getattr(item, "text_body", "") or getattr(item, "body", "") or "")
            date = str(getattr(item, "datetime_received", "") or "(无时间)")
            if query and not _matches_text_query(" ".join([subject, sender, body]), query):
                continue
            attachments = [str(getattr(att, "name", "")) for att in getattr(item, "attachments", []) if getattr(att, "name", "")]
            lines.append(
                f"来源邮箱：{_mail_source_label(account)}\n"
                f"邮件到达时间：{date}\n"
                f"发件人：{sender}\n"
                f"标题：{subject}\n"
                f"摘要：{_summarize_text(_html_to_text(body))}\n"
                f"附件：{', '.join(attachments) if attachments else '无'}"
            )
        if not lines:
            return f"未找到匹配邮件：{query}" if query else "当前 Exchange 邮箱没有邮件。"
        return "\n\n".join(lines)
    except Exception as exc:
        return f"Exchange 邮箱读取失败：{exc}"


def _fetch_recent_exchange_items(account: dict[str, Any], *, limit: int = 30) -> list[dict[str, Any]]:
    try:
        from exchangelib import Account, Configuration, Credentials, DELEGATE  # type: ignore
    except Exception as exc:
        raise RuntimeError("Exchange 邮箱需要安装可选依赖 exchangelib 后才能通过 EWS 读取。") from exc

    server = str(account.get("imap_host") or "")
    username = str(account.get("username") or account.get("email_address") or "")
    password = str(account.get("password") or "")
    email_address = str(account.get("email_address") or username)
    credentials = Credentials(username=username, password=password)
    config = Configuration(server=server, credentials=credentials) if server else None
    mailbox = Account(
        primary_smtp_address=email_address,
        config=config,
        credentials=credentials if config is None else None,
        autodiscover=config is None,
        access_type=DELEGATE,
    )
    items: list[dict[str, Any]] = []
    for item in mailbox.inbox.all().order_by("-datetime_received")[: max(1, min(int(limit or 30), 100))]:
        subject = str(getattr(item, "subject", "") or "(无标题)")
        sender_obj = getattr(item, "sender", None)
        sender = str(getattr(sender_obj, "email_address", "") or getattr(sender_obj, "name", "") or "(未知发件人)")
        body = str(getattr(item, "text_body", "") or getattr(item, "body", "") or "")
        date = str(getattr(item, "datetime_received", "") or "(无时间)")
        attachments = [str(getattr(att, "name", "")) for att in getattr(item, "attachments", []) if getattr(att, "name", "")]
        message_id = str(getattr(item, "message_id", "") or getattr(item, "id", "") or "")
        received_at_ts = _date_to_timestamp(date)
        message_key = _mail_message_key(
            account,
            message_id=message_id,
            date=date,
            sender=sender,
            subject=subject,
            fallback_key=str(getattr(item, "id", "") or subject),
        )
        items.append(
            {
                "message_key": message_key,
                "received_at": date,
                "received_at_ts": received_at_ts,
                "sender": sender,
                "subject": subject,
                "summary": "",
                "attachments": [],
                "text": "",
                "_body": _html_to_text(body),
                "_attachments": attachments,
            }
        )
    return items


def _imap_search_criteria(query: str) -> tuple[str, ...]:
    q = _clean(query)
    if not q or q in {"today", "今天", "最近"}:
        return ("ALL",)
    if q in {"未读", "unread"}:
        return ("UNSEEN",)
    escaped = q.replace("\\", "\\\\").replace('"', '\\"')
    return (f'(OR SUBJECT "{escaped}" FROM "{escaped}")',)


def _format_mail_summary(msg: email.message.Message, *, account: dict[str, Any] | None = None) -> str:
    date = _decode_header_value(msg.get("Date", "(无时间)"))
    sender = _decode_header_value(msg.get("From", "(未知发件人)"))
    subject = _decode_header_value(msg.get("Subject", "(无标题)"))
    body = _body_text(msg)
    attachments = _attachments(msg)
    summary = _summarize_text(body, subject=subject, sender=sender)
    return _format_mail_item(account, date, sender, subject, summary, attachments)


def _mail_item_from_message(
    msg: email.message.Message,
    *,
    account: dict[str, Any],
    fallback_key: str,
    raw: bytes | None = None,
    include_summary: bool = True,
) -> dict[str, Any]:
    date = _decode_header_value(msg.get("Date", "(无时间)"))
    sender = _decode_header_value(msg.get("From", "(未知发件人)"))
    subject = _decode_header_value(msg.get("Subject", "(无标题)"))
    attachments = _attachments(msg) if include_summary else []
    summary = _summarize_text(_body_text(msg), subject=subject, sender=sender) if include_summary else ""
    message_key = _mail_message_key(
        account,
        message_id=_decode_header_value(msg.get("Message-ID", "")),
        date=date,
        sender=sender,
        subject=subject,
        fallback_key=fallback_key,
    )
    return {
        "message_key": message_key,
        "received_at": date,
        "received_at_ts": _date_to_timestamp(date),
        "sender": sender,
        "subject": subject,
        "summary": summary,
        "attachments": attachments,
        "text": _format_mail_item(account, date, sender, subject, summary, attachments) if include_summary else "",
        "_raw_message": raw,
    }


def _format_mail_item(
    account: dict[str, Any] | None,
    date: str,
    sender: str,
    subject: str,
    summary: str,
    attachments: list[str],
) -> str:
    source_line = f"来源邮箱：{_mail_source_label(account)}\n" if account else ""
    return (
        f"{source_line}"
        f"邮件到达时间：{date}\n"
        f"发件人：{sender}\n"
        f"标题：{subject}\n"
        f"摘要：{summary}\n"
        f"附件：{', '.join(attachments) if attachments else '无'}"
    )


def _matches_query(msg: email.message.Message, query: str) -> bool:
    q = _clean(query).lower()
    if not q or q in {"today", "今天", "最近"}:
        return True
    haystack = " ".join(
        [
            _decode_header_value(msg.get("From", "")),
            _decode_header_value(msg.get("Subject", "")),
            _body_text(msg)[:1000],
        ]
    ).lower()
    return q in haystack


def _matches_text_query(text: str, query: str) -> bool:
    q = _clean(query).lower()
    return not q or q in {"today", "今天", "最近"} or q in str(text or "").lower()


def _decode_header_value(value: Any) -> str:
    out: list[str] = []
    for data, charset in decode_header(str(value or "")):
        if isinstance(data, bytes):
            out.append(data.decode(charset or "utf-8", errors="replace"))
        else:
            out.append(data)
    return "".join(out).strip()


def _body_text(msg: email.message.Message) -> str:
    parts = msg.walk() if msg.is_multipart() else [msg]
    html_body = ""
    for part in parts:
        if part.get_content_disposition() == "attachment":
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        if part.get_content_type() == "text/plain":
            return text.strip()
        if part.get_content_type() == "text/html" and not html_body:
            html_body = _html_to_text(text)
    return html_body.strip() or "(无正文)"


def _attachments(msg: email.message.Message) -> list[str]:
    names: list[str] = []
    for part in msg.walk() if msg.is_multipart() else []:
        name = part.get_filename()
        if name:
            names.append(_decode_header_value(name))
    return names


def _summarize_text(text: str, max_chars: int = 120, *, subject: str = "", sender: str = "") -> str:
    cleaned = _clean_mail_body_for_summary(text)
    if not cleaned:
        return "未读取到可摘要的正文内容。"
    llm_summary = _llm_mail_body_summary(cleaned, subject=subject, sender=sender)
    if llm_summary:
        return llm_summary[:max_chars].strip()
    normalized = re.sub(r"\s+", " ", html.unescape(cleaned or "")).strip()
    return _local_mail_body_summary(normalized, max_chars=max_chars)


def _clean_mail_body_for_summary(text: str) -> str:
    """Remove signatures, quoted history, and transport headers before summary."""
    raw = html.unescape(text or "").replace("\r\n", "\n").replace("\r", "\n")
    raw = raw.replace("\u00a0", " ")
    raw = _drop_forwarded_preamble(raw)
    lines: list[str] = []
    for line in raw.split("\n"):
        stripped = line.strip()
        if not stripped:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        stripped = _strip_inline_forward_header(stripped)
        if not stripped:
            continue
        compact = re.sub(r"\s+", "", stripped).lower()
        if _looks_like_mail_noise_line(stripped, compact):
            continue
        if _looks_like_email_header_or_recipient_line(stripped):
            continue
        if stripped.startswith((">", "｜", "|")):
            continue
        lines.append(stripped)

    cleaned = "\n".join(lines)
    cleaned = re.split(
        r"(?im)^\s*(此致|Best regards|Regards|Thanks|谢谢|祝好)[,，。!！ ]*$",
        cleaned,
        maxsplit=1,
    )[0]
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def _local_mail_body_summary(text: str, *, max_chars: int = 120) -> str:
    normalized = re.sub(r"\s+", " ", html.unescape(text or "")).strip()
    normalized = re.sub(r"^(各位领导|各位同事|您好|你好)[:：，,\s]*", "", normalized).strip()
    normalized = re.sub(r"^(上午好|下午好|晚上好|您好|你好)[!！。,\s]*", "", normalized).strip()
    match = re.search(r"附件为(?:本次|此次)?(.{4,80}?)(?:，|,)?请(?:查阅|查看|审阅)[!！。,\s]*(?:并)?(?:对照)?(?:做好)?(.{0,40}?)(?:。|$)", normalized)
    if match:
        subject = match.group(1).strip(" ，,。")
        action = match.group(2).strip(" ，,。") or "相关准备"
        summary = f"邮件发送{subject}，请查阅并做好{action}。"
        return summary[:max_chars].strip()
    match = re.search(r"附件为(?:本次|此次)?(.{4,80}?)(?:，|,)(请.{4,80}?)(?:。|！|!|$)", normalized)
    if match:
        subject = match.group(1).strip(" ，,。")
        action = match.group(2).strip(" ，,。")
        summary = f"邮件发送{subject}，{action}。"
        return summary[:max_chars].strip()
    match = re.search(r"(请|需|需要)(.{4,90}?)(?:。|！|!|$)", normalized)
    if match:
        return (match.group(0).strip(" ，,") or normalized)[:max_chars].strip()
    return normalized[:max_chars].strip()


def _drop_forwarded_preamble(text: str) -> str:
    parts = re.split(
        r"(?im)^[-_\s]*(转发的原邮件|Forwarded message|Original Message)[-_\s]*$",
        text,
        maxsplit=1,
    )
    if len(parts) >= 3:
        return parts[-1]
    return text


def _looks_like_mail_noise_line(line: str, compact_lower: str) -> bool:
    email_count = _email_address_count(line)
    patterns = (
        r"^[-_\s]{2,}.{0,80}[-_\s]{2,}$",
        r"^[-_]{2,}\s*(转发的原邮件|Forwarded message|Original Message)\s*[-_]{2,}$",
        r"^(发件人|收件人|抄送|主题|日期|时间|From|To|Cc|Subject|Date|Sent)\s*[:：<]",
        r"(发件人|收件人|抄送|日期|时间)\s*[<:：].+@.+",
        r"^On .+ wrote:$",
        r".+写道[:：]$",
        r"^mailto:",
        r"^https?://",
        r"^\+?\d[\d\s\-()]{6,}$",
        r"^[\w.\-+]+@[\w.\-]+\.\w+$",
    )
    if any(re.search(pattern, line, re.IGNORECASE) for pattern in patterns):
        return True
    if any(token in compact_lower for token in ("----转发的原邮件----", "-----originalmessage-----", "-----forwardedmessage-----")):
        return True
    if email_count >= 2:
        return True
    signature_markers = ("综合管理部", "有限公司", "电话", "手机", "邮箱", "email", "tel", "mobile")
    has_contact = "@" in line or bool(re.search(r"\+?\d[\d\s\-]{7,}", line))
    return bool(has_contact and any(marker.lower() in compact_lower for marker in signature_markers))


def _looks_like_email_header_or_recipient_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if "@" in stripped:
        return True
    return bool(re.match(r"^(主题|Subject)\s*[:：]?.{0,200}$", stripped, re.IGNORECASE))


def _strip_inline_forward_header(line: str) -> str:
    """Drop packed mail-client forwarding/contact headers while preserving body lines."""
    stripped = line.strip()
    if not stripped:
        return ""
    stripped = re.sub(
        r"(?i)^[-_\s]*(转发的原邮件|Forwarded message|Original Message)[-_\s]*",
        "",
        stripped,
    ).strip()
    if re.fullmatch(r"[-_\s]{2,}.{0,80}[-_\s]{2,}", stripped):
        return ""
    if not stripped:
        return ""
    if _email_address_count(stripped) >= 2:
        return ""
    if re.search(r"(发件人|收件人|抄送|日期|时间)\s*[<:：].+@", stripped, re.IGNORECASE):
        return ""
    return stripped


def _email_address_count(text: str) -> int:
    return len(re.findall(r"[\w.\-+']+@[\w.\-]+\.\w+", text or ""))


def _mail_account_id(platform: str, user_id: str, email_address: str) -> str:
    raw = f"{_clean(platform or 'wecom')}|{_clean(user_id)}|{_clean(email_address).lower()}"
    return "mail-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _mail_source_label(account: dict[str, Any] | None) -> str:
    if not account:
        return "未知邮箱"
    label = _clean(account.get("account_label"))
    address = _clean(account.get("email_address") or account.get("username"))
    if label and address:
        return f"{label} <{address}>"
    return label or address or "未知邮箱"


def _with_source_context(account: dict[str, Any], body: str) -> str:
    if str(body or "").lstrip().startswith("来源邮箱："):
        return body
    return f"【来源邮箱：{_mail_source_label(account)}】\n{body}"


def _mail_message_key(
    account: dict[str, Any],
    *,
    message_id: str = "",
    date: str = "",
    sender: str = "",
    subject: str = "",
    fallback_key: str = "",
) -> str:
    stable = _clean(message_id) or "|".join([_clean(date), _clean(sender), _clean(subject), _clean(fallback_key)])
    raw = f"{_clean(account.get('account_id'))}|{stable}"
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()


def _date_to_timestamp(value: str) -> float:
    try:
        parsed = parsedate_to_datetime(str(value or ""))
        return parsed.timestamp()
    except Exception:
        return 0.0


def _first_run_notify_seconds() -> int:
    try:
        return max(0, int(os.environ.get("ANT_COLONY_MAIL_FIRST_RUN_NOTIFY_SECONDS", "600") or 0))
    except Exception:
        return 600


def _mail_notifier_lock_path() -> str:
    configured = _clean(os.environ.get("ANT_COLONY_MAIL_NOTIFIER_LOCK"))
    if configured:
        return configured
    db_path = os.environ.get("ANT_COLONY_DB_PATH", "./data/ant-colony.db")
    base_dir = os.path.dirname(os.path.abspath(db_path)) or os.path.abspath("./data")
    return os.path.join(base_dir, "mail-new-message-notifier.lock")


def _acquire_mail_notifier_lock() -> str | None:
    path = _mail_notifier_lock_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    stale_after = max(120, int(os.environ.get("ANT_COLONY_MAIL_NOTIFIER_LOCK_STALE_SECONDS", "900") or 900))
    now = time.time()
    try:
        if os.path.exists(path):
            pid = _read_mail_notifier_lock_pid(path)
            if (pid and not _process_is_alive(pid)) or now - os.path.getmtime(path) > stale_after:
                os.remove(path)
    except Exception:
        pass
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(f"{os.getpid()} {now}\n")
    return path


def _read_mail_notifier_lock_pid(path: str) -> int:
    try:
        first = open(path, "r", encoding="utf-8").read(64).strip().split()[0]
        return int(first)
    except Exception:
        return 0


def _process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False


def _release_mail_notifier_lock(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except Exception as exc:
        logger.warning("failed to release mail notifier lock %s: %s", path, exc)


def _mail_notification_state(conn: Any, account_id: str) -> Any:
    return conn.execute(
        "SELECT * FROM mail_notification_state WHERE account_id=?",
        (_clean(account_id),),
    ).fetchone()


def _upsert_mail_notification_state(conn: Any, account_id: str, now: float, error: str) -> None:
    conn.execute(
        """
        INSERT INTO mail_notification_state (account_id,last_polled_at,last_error,created_at,updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(account_id) DO UPDATE SET
            last_polled_at=excluded.last_polled_at,
            last_error=excluded.last_error,
            updated_at=excluded.updated_at
        """,
        (_clean(account_id), now, _clean(error), now, now),
    )


def _mail_notification_event_exists(conn: Any, account_id: str, message_key: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM mail_notification_events WHERE account_id=? AND message_key=?",
        (_clean(account_id), _clean(message_key)),
    ).fetchone()
    return row is not None


def _record_mail_notification_event(
    conn: Any,
    account: dict[str, Any],
    item: dict[str, Any],
    status: str,
    error: str = "",
) -> None:
    now = time.time()
    conn.execute(
        """
        INSERT INTO mail_notification_events (
            account_id,message_key,platform,user_id,source_label,subject,sender,received_at,received_at_ts,
            delivery_status,delivery_error,created_at,updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(account_id, message_key) DO UPDATE SET
            delivery_status=excluded.delivery_status,
            delivery_error=excluded.delivery_error,
            updated_at=excluded.updated_at
        """,
        (
            _clean(account.get("account_id")),
            _clean(item.get("message_key")),
            _clean(account.get("platform") or "wecom"),
            _clean(account.get("user_id")),
            _mail_source_label(account),
            _clean(item.get("subject")),
            _clean(item.get("sender")),
            _clean(item.get("received_at")),
            float(item.get("received_at_ts") or 0),
            status,
            error,
            now,
            now,
        ),
    )


def _assistant_allows_notification(platform: str, user_id: str) -> bool:
    if not platform or not user_id:
        return False
    conn = Database.get().connect()
    try:
        row = conn.execute(
            """
            SELECT status
            FROM employee_bot_assignments
            WHERE platform = ? AND user_id = ?
            """,
            (_clean(platform), _clean(user_id)),
        ).fetchone()
    except Exception:
        return False
    if not row:
        return False
    return str(row["status"] or "") == "active"


def _send_mail_notification(account: dict[str, Any], item: dict[str, Any]) -> bool:
    from src.gateway import provider_outbound

    text = (
        "【新邮件提醒】\n"
        "你有一封新邮件到达。\n\n"
        "可回复“汇总今天邮件”查看近期邮件摘要。AI 助手只提醒和查询，不代发邮件或回复邮件。"
    )
    return provider_outbound.send_platform_text(
        _clean(account.get("platform") or "wecom"),
        _clean(account.get("user_id")),
        text,
    )


def _hydrate_mail_item_for_notification(account: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    if item.get("text") and item.get("summary"):
        return item
    raw = item.get("_raw_message")
    if isinstance(raw, bytes) and raw:
        hydrated = _mail_item_from_message(
            email.message_from_bytes(raw),
            account=account,
            fallback_key=str(item.get("message_key") or ""),
            raw=raw,
            include_summary=True,
        )
        hydrated["message_key"] = item.get("message_key") or hydrated["message_key"]
        return hydrated
    pop3_number = str(item.get("_pop3_number") or "")
    if pop3_number:
        raw = _retrieve_pop3_raw_message(account, pop3_number)
        if raw:
            hydrated = _mail_item_from_message(
                email.message_from_bytes(raw),
                account=account,
                fallback_key=str(item.get("_pop3_uid") or item.get("message_key") or pop3_number),
                raw=raw,
                include_summary=True,
            )
            hydrated["message_key"] = item.get("message_key") or hydrated["message_key"]
            return hydrated
    body = str(item.get("_body") or "")
    attachments = [str(x) for x in item.get("_attachments") or []]
    summary = _summarize_text(body, subject=str(item.get("subject") or ""), sender=str(item.get("sender") or ""))
    hydrated = {**item, "summary": summary, "attachments": attachments}
    hydrated["text"] = _format_mail_item(
        account,
        str(item.get("received_at") or "(无时间)"),
        str(item.get("sender") or "(未知发件人)"),
        str(item.get("subject") or "(无标题)"),
        summary,
        attachments,
    )
    return hydrated


def _retrieve_pop3_raw_message(account: dict[str, Any], number: str) -> bytes:
    host = str(account.get("imap_host") or "")
    port = int(account.get("imap_port") or 995)
    username = str(account.get("username") or account.get("email_address") or "")
    password = str(account.get("password") or "")
    encryption = _account_encryption(account)
    client = poplib.POP3_SSL(host, port, timeout=20) if encryption == "ssl_tls" else poplib.POP3(host, port, timeout=20)
    try:
        if encryption == "starttls":
            client.stls()
        client.user(username)
        client.pass_(password)
        _, lines, _ = client.retr(int(number))
        return b"\n".join(line if isinstance(line, bytes) else str(line).encode("utf-8") for line in lines)
    finally:
        try:
            client.quit()
        except Exception:
            pass


def _llm_mail_body_summary(text: str, *, subject: str = "", sender: str = "") -> str:
    if os.environ.get("ANT_COLONY_MAIL_LLM_SUMMARY", "1").strip().lower() in {"0", "false", "off"}:
        return ""
    try:
        from src.config.bootstrap import build_settings_service

        snapshot = build_settings_service().build_runtime_snapshot()
        enabled_profiles = [p for p in snapshot.llm_profiles if getattr(p, "enabled", False) and getattr(p, "api_key", "")]
        default_profiles = [p for p in enabled_profiles if bool((getattr(p, "metadata", {}) or {}).get("is_default"))]
        profiles = default_profiles + [p for p in enabled_profiles if p not in default_profiles]
        for profile in profiles:
            profile_key = str(getattr(profile, "profile_id", getattr(profile, "model_name", "unknown")))
            failed_at = _MAIL_LLM_PROFILE_FAILURES.get(profile_key, 0)
            if failed_at and time.time() - failed_at < _MAIL_LLM_FAILURE_TTL_SECONDS:
                continue
            try:
                summary = _call_mail_summary_profile(profile, text=text, subject=subject, sender=sender)
                if summary:
                    return summary
                _MAIL_LLM_PROFILE_FAILURES[profile_key] = time.time()
            except Exception as exc:
                _MAIL_LLM_PROFILE_FAILURES[profile_key] = time.time()
                logger.warning(
                    "mail LLM profile %s failed, trying next profile: %s",
                    profile_key,
                    exc,
                )
        return ""
    except Exception as exc:
        logger.warning("mail LLM summary failed, using local fallback: %s", exc)
        return ""


def _call_mail_summary_profile(profile: Any, *, text: str, subject: str = "", sender: str = "") -> str:
    system_prompt = (
        "你是企业邮箱摘要助手。只根据邮件正文生成简短中文摘要。"
        "不要复述邮件头、签名、联系方式、转发分隔线或引用历史。"
        "输出 1 到 2 句，最多 120 个中文字符；如果正文没有有效内容，输出“未读取到可摘要的正文内容”。"
    )
    user_prompt = f"邮件主题：{subject}\n发件人：{sender}\n\n邮件正文：\n{text[:4000]}"
    provider = str(getattr(profile, "provider", "") or "openai").lower()
    model_name = str(getattr(profile, "model_name", "") or "")
    api_key = str(getattr(profile, "api_key", "") or "")
    api_base = str(getattr(profile, "api_base", "") or "")
    if provider == "anthropic":
        import anthropic

        client = anthropic.Anthropic(api_key=api_key, timeout=20)
        resp = client.messages.create(
            model=model_name,
            max_tokens=220,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = "\n".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
    else:
        from openai import OpenAI

        kwargs: dict[str, Any] = {"api_key": api_key, "timeout": 20}
        if api_base:
            kwargs["base_url"] = api_base
        try:
            from src.platform.model_management_service import normalize_model_name_for_api

            model_name = normalize_model_name_for_api(model_name, api_base)
        except Exception:
            pass
        client = OpenAI(**kwargs)
        resp = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=220,
        )
        raw = resp.choices[0].message.content or ""
    cleaned = re.sub(r"\s+", " ", str(raw or "")).strip()
    cleaned = re.sub(r"^(摘要|邮件摘要)\s*[:：]\s*", "", cleaned)
    if _summary_looks_like_mail_header(cleaned):
        return ""
    return cleaned[:120] if cleaned else ""


def _summary_looks_like_mail_header(text: str) -> bool:
    compact = re.sub(r"\s+", "", text or "").lower()
    if _email_address_count(text) >= 2:
        return True
    return any(
        token in compact
        for token in (
            "----转发的原邮件----",
            "-----originalmessage-----",
            "发件人<",
            "收件人",
            "抄送",
        )
    )


def _html_to_text(raw: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>", "\n", raw)
    text = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text)


def _extract_raw_message(msg_data: Any) -> bytes | None:
    for item in msg_data or []:
        if isinstance(item, tuple) and len(item) > 1 and isinstance(item[1], bytes):
            return item[1]
    return None


def _public_account(row: dict[str, Any]) -> dict[str, Any]:
    encryption = _account_encryption(row)
    return {
        "platform": row.get("platform", ""),
        "user_id": row.get("user_id", ""),
        "user_name": row.get("user_name", "") if "user_name" in row else _user_display_name(str(row.get("platform") or ""), str(row.get("user_id") or "")),
        "email_address": row.get("email_address", ""),
        "account_id": row.get("account_id", ""),
        "account_label": row.get("account_label", ""),
        "protocol": row.get("protocol", "imap"),
        "imap_host": row.get("imap_host", ""),
        "imap_port": int(row.get("imap_port") or 993),
        "imap_ssl": encryption == "ssl_tls",
        "encryption": encryption,
        "username": row.get("username", ""),
        "folder": row.get("folder", "INBOX"),
        "poll_interval_minutes": int(row.get("poll_interval_minutes") or 1),
        "enabled": bool(row.get("enabled", 1)),
        "password_configured": bool(row.get("password")),
        "updated_by": row.get("updated_by", ""),
        "updated_at": row.get("updated_at", 0),
    }


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _user_display_name(platform: str, user_id: str) -> str:
    if not platform or not user_id:
        return ""
    row = _conn().execute(
        "SELECT name FROM org_users WHERE platform=? AND user_id=?",
        (platform, user_id),
    ).fetchone()
    return str(row[0] or "") if row else ""


def _normalize_protocol(value: Any) -> str:
    normalized = _clean(value).lower()
    aliases = {"ews": "exchange", "graph": "exchange", "microsoft365": "exchange", "office365": "exchange"}
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in {"imap", "pop3", "exchange"} else "imap"


def _normalize_encryption(value: Any, *, legacy_ssl: Any = None) -> str:
    normalized = _clean(value).lower().replace(" ", "")
    aliases = {
        "ssl": "ssl_tls",
        "tls": "ssl_tls",
        "ssl/tls": "ssl_tls",
        "ssltls": "ssl_tls",
        "implicit_tls": "ssl_tls",
        "隐式加密": "ssl_tls",
        "starttls": "starttls",
        "显式tls": "starttls",
        "plain": "none",
        "none": "none",
        "无加密": "none",
        "不加密": "none",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized in {"ssl_tls", "starttls", "none"}:
        return normalized
    if legacy_ssl is not None:
        return "ssl_tls" if bool(legacy_ssl) else "none"
    # Existing saved accounts used a checked SSL/TLS box. Keep that behavior only
    # when no new encryption value has been supplied, so upgrades are non-breaking.
    return "ssl_tls"


def _default_mail_port(protocol: Any, encryption: Any) -> int:
    normalized_protocol = _normalize_protocol(protocol or "imap")
    normalized_encryption = _normalize_encryption(encryption)
    if normalized_protocol == "pop3":
        return 995 if normalized_encryption == "ssl_tls" else 110
    if normalized_protocol == "exchange":
        return 443
    return 993 if normalized_encryption == "ssl_tls" else 143


def _account_encryption(account: dict[str, Any]) -> str:
    return _normalize_encryption(account.get("encryption"), legacy_ssl=account.get("imap_ssl"))


def _mail_connection_error(protocol: str, encryption: str, exc: Exception) -> str:
    detail = str(exc)
    upper_detail = detail.upper()
    if _is_auth_error(detail):
        return (
            f"{protocol} 邮箱读取失败：账号或密码/授权码不正确，或该邮箱没有开启 POP3/IMAP/客户端授权。"
            "请在管理员后台重新保存该邮箱的正确密码或客户端授权码，并确认邮箱后台允许该协议登录后再测试。"
        )
    if "WRONG_VERSION_NUMBER" in upper_detail:
        return (
            f"{protocol} 邮箱读取失败：服务器不接受当前的 SSL/TLS 连接方式。"
            "请在管理员后台把“连接加密方式”改为“不加密”或“STARTTLS”，并按邮箱服务商提供的端口重新测试。"
        )
    return f"{protocol} 邮箱读取失败：{detail}"
