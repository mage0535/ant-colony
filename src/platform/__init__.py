from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def _try_feishu():
    if not (os.environ.get("FEISHU_APP_ID") and os.environ.get("FEISHU_APP_SECRET")):
        return None
    from src.platform.api_feishu import FeishuClient
    try:
        return FeishuClient()
    except Exception as e:
        logger.warning("Feishu client failed: %s", e)
    return None


def _try_dingtalk():
    if not (os.environ.get("DINGTALK_CLIENT_ID") and os.environ.get("DINGTALK_CLIENT_SECRET")):
        return None
    from src.platform.api_dingtalk import DingTalkClient
    try:
        return DingTalkClient()
    except Exception as e:
        logger.warning("DingTalk client failed: %s", e)
    return None


def _try_wecom():
    if not os.environ.get("WECOM_CORP_ID") or not os.environ.get("WECOM_SECRET"):
        return None
    from src.platform.api_wecom import WeComClient
    try:
        return WeComClient()
    except Exception as e:
        logger.warning("WeCom client failed: %s", e)
    return None


def _collect(label: str, fn_name: str, *args, **kwargs) -> list[str]:
    lines = []
    for platform_id, try_fn, name in [
        ("feishu", _try_feishu, "飞书"),
        ("dingtalk", _try_dingtalk, "钉钉"),
        ("wecom", _try_wecom, "企业微信"),
    ]:
        client = try_fn()
        if not client:
            continue
        try:
            method = getattr(client, fn_name)
            r = method(*args, **kwargs)
            if r:
                lines.append(f"[{name}] {r}")
        except Exception as e:
            lines.append(f"[{name}] {e}")
    return lines


def contact_search(query: str) -> str:
    lines = _collect("联系人", "search_user", query)
    return "\n".join(lines) if lines else "未找到匹配的联系人"


def calendar_agenda(days: int = 7) -> str:
    lines = _collect("日程", "get_agenda", days)
    return "\n".join(lines) if lines else "未找到日程信息（需配置飞书/钉钉/企微凭证）"


def doc_search(query: str) -> str:
    lines = _collect("文档", "search_docs", query)
    return "\n".join(lines) if lines else "未找到匹配的文档（需配置飞书/钉钉/企微凭证）"


def approval_list(status: str = "pending") -> str:
    lines = []
    for client_fn, name in [(_try_feishu, "飞书"), (_try_dingtalk, "钉钉")]:
        client = client_fn()
        if not client:
            continue
        try:
            r = client.list_approvals(status)
            if r:
                lines.append(f"[{name}] {r}")
        except Exception as e:
            lines.append(f"[{name}] {e}")
    return "\n".join(lines) if lines else "无待审批事项（需配置飞书/钉钉凭证）"


def calendar_create(summary: str, start_at: str, end_at: str) -> str:
    lines = _collect("创建日程", "create_event", summary, start_at, end_at)
    return "\n".join(lines) if lines else "创建日程失败（需配置飞书/钉钉/企微凭证）"


def create_doc(title: str, content: str = "") -> str:
    wecom = _try_wecom()
    if not wecom:
        return "需配置企业微信凭证"
    try:
        r = wecom.create_doc(title, content)
        return r or "文档创建成功"
    except Exception as e:
        return f"创建文档失败: {e}"


def list_meetings() -> str:
    lines = []
    for client_fn, name in [(_try_wecom, "企业微信"), (_try_dingtalk, "钉钉")]:
        client = client_fn()
        if not client:
            continue
        try:
            r = client.list_meetings() if hasattr(client, 'list_meetings') else None
            if r:
                lines.append(f"[{name}] {r}")
        except Exception as e:
            lines.append(f"[{name}] {e}")
    return "\n".join(lines) if lines else "未找到会议信息（需配置企微/钉钉凭证）"


def create_meeting(title: str, start_at: str, end_at: str, attendees: str = "") -> str:
    attendee_list = [a.strip() for a in attendees.split(",") if a.strip()] if attendees else []
    lines = []
    for client_fn, name in [(_try_wecom, "企业微信")]:
        client = client_fn()
        if not client:
            continue
        try:
            r = client.create_meeting(title, start_at, end_at, attendee_list)
            if r:
                lines.append(f"[{name}] {r}")
        except Exception as e:
            lines.append(f"[{name}] {e}")
    return "\n".join(lines) if lines else "创建会议失败（需配置企微凭证）"


def who_is_admin() -> str:
    """Return PLATFORM ADMINS only (not department leaders)."""
    lines = []
    for client_fn, name in [(_try_feishu, "飞书"), (_try_dingtalk, "钉钉"), (_try_wecom, "企业微信")]:
        client = client_fn()
        if not client:
            continue
        try:
            r = client.get_admin_users()
            if r:
                lines.append(f"[{name}]\n{r}")
        except Exception as e:
            lines.append(f"[{name}] 查询失败: {e}")
    return "\n\n".join(lines) if lines else "未配置平台管理员信息"


def who_is_leader() -> str:
    """Return DEPARTMENT LEADERS only (not platform admins)."""
    lines = []
    for client_fn, name in [(_try_wecom, "企业微信")]:
        client = client_fn()
        if not client:
            continue
        try:
            r = client.get_department_leaders()
            if r:
                lines.append(f"[{name}]\n{r}")
        except Exception as e:
            lines.append(f"[{name}] 查询失败: {e}")
    return "\n\n".join(lines) if lines else "未查询到部门负责人信息（需配置企微凭证）"
