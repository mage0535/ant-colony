from __future__ import annotations

import os
from urllib.parse import urlencode

from src.web import admin_auth


_KNOWLEDGE_TRIGGERS = (
    "知识库",
    "打开知识库",
    "知识库后台",
    "知识后台",
    "知识库管理",
    "进入知识库",
    "我的知识库",
    "上传文档入库",
    "打开后台知识库",
)
_ADMIN_TRIGGERS = (
    "打开管理员控制台",
    "管理员控制台",
    "管理后台",
    "管理员后台",
    "进入后台",
    "打开后台",
    "后台",
    "开通员工助手",
    "平台管理",
)
_MENU_TRIGGERS = (
    "菜单",
    "帮助",
    "入口",
    "后台入口",
    "功能菜单",
)


def build_entry_link_reply(platform: str, user_id: str, text: str) -> str | None:
    normalized_platform = _normalize_platform(platform)
    normalized_user_id = user_id.strip()
    normalized_text = _normalize_text(text)
    if not normalized_user_id or not normalized_text:
        return None
    knowledge_match = _matches(normalized_text, _KNOWLEDGE_TRIGGERS)
    admin_match = _matches(normalized_text, _ADMIN_TRIGGERS)
    if _matches(normalized_text, _MENU_TRIGGERS):
        return _menu_reply(normalized_platform, normalized_user_id)
    # 用户明确提到知识库时，优先返回知识库入口，避免“后台”泛词误进管理员控制台。
    if knowledge_match:
        return _knowledge_reply(normalized_platform, normalized_user_id)
    if admin_match:
        if not (admin_auth.is_platform_admin(normalized_platform, normalized_user_id) or admin_auth.is_hr_specialist(normalized_platform, normalized_user_id)):
            return "你当前没有管理员权限或人事专员权限，不能打开后台控制台。你可以发送“打开知识库”进入自己的知识库管理页面。"
        return _admin_reply(normalized_platform, normalized_user_id)
    return None


def is_entry_menu_command(text: str) -> bool:
    """Only match short obvious menu commands for zero-cost pre-filter."""
    normalized = _normalize_text(text)
    if len(normalized) > 4:
        return False
    return normalized in {_normalize_text(item) for item in _MENU_TRIGGERS}


def build_platform_entry_menu(platform: str, user_id: str, *, is_admin: bool = False) -> dict[str, object]:
    normalized_platform = _normalize_platform(platform)
    items = [
        {
            "key": "knowledge_user",
            "title": "知识库管理",
            "description": "查看、上传和维护自己权限范围内的知识库",
            "url": _knowledge_url(normalized_platform, user_id),
        },
        {
            "key": "upload_knowledge",
            "title": "上传文档入库",
            "description": "打开知识库页面后选择文件上传，系统自动解析并索引",
            "url": _knowledge_url(normalized_platform, user_id),
        },
    ]
    is_hr = admin_auth.is_hr_specialist(normalized_platform, user_id)
    if is_admin or is_hr:
        items.append(
            {
                "key": "admin_console",
                "title": "管理员控制台" if is_admin else "人事专员后台",
                "description": "平台 Bot、员工助手、公司级知识库、邮箱、业务系统和集成管理" if is_admin else "进入审批假期管理，查看和调整员工假期额度",
                "url": _admin_url(normalized_platform, user_id),
            }
        )
    return {"platform": normalized_platform, "user_id": user_id, "items": items}


def build_platform_entry_payloads(platform: str, user_id: str, *, is_admin: bool = False) -> dict[str, object]:
    menu = build_platform_entry_menu(platform, user_id, is_admin=is_admin)
    items = menu["items"]
    lines = ["可用入口："]
    for index, item in enumerate(items, start=1):
        lines.append(f"{index}. {item['title']}：{item['url']}")
    text = "\n".join(lines)
    return {
        "platform": menu["platform"],
        "user_id": user_id,
        "text": text,
        "menu": menu,
        "feishu_card": _build_feishu_entry_card(items),
        "dingtalk_card": _build_dingtalk_entry_card(items),
    }


def _knowledge_reply(platform: str, user_id: str) -> str:
    platform = _normalize_platform(platform)
    return (
        "知识库管理入口：\n"
        f"{_knowledge_url(platform, user_id)}\n\n"
        "进入后可以查看组织目录、上传文档入库，并按你的企业 IM 权限管理知识内容。"
    )


def _admin_reply(platform: str, user_id: str) -> str:
    platform = _normalize_platform(platform)
    title = "管理员控制台入口" if admin_auth.is_platform_admin(platform, user_id) else "人事专员后台入口"
    description = (
        "进入后可以开通平台 Bot、管理员工 AI 助手、导入公司说明书、管理公司级知识库、配置邮箱、业务系统和外部集成。"
        if admin_auth.is_platform_admin(platform, user_id)
        else "进入后可以使用审批假期管理，查看员工动态假期提示、调整假期额度、处理负数假期和运行审批假期同步。"
    )
    return (
        f"{title}：\n"
        f"{_admin_url(platform, user_id)}\n\n"
        f"{description}"
    )


def _menu_reply(platform: str, user_id: str) -> str:
    platform = _normalize_platform(platform)
    is_admin = admin_auth.is_platform_admin(platform, user_id)
    payloads = build_platform_entry_payloads(platform, user_id, is_admin=is_admin)
    return str(payloads["text"])


def _knowledge_url(platform: str, user_id: str) -> str:
    platform = _normalize_platform(platform)
    token = admin_auth.create_im_user_token(platform=platform, user_id=user_id, ttl_seconds=_ttl_seconds())
    query = urlencode({"platform": platform, "user_id": user_id, "user_token": token})
    return f"{_base_url()}/knowledge/user?{query}"


def _admin_url(platform: str, user_id: str) -> str:
    platform = _normalize_platform(platform)
    token = admin_auth.create_admin_console_token(platform=platform, user_id=user_id, ttl_seconds=_ttl_seconds())
    query = urlencode({"platform": platform, "user_id": user_id, "admin_token": token})
    return f"{_base_url()}/admin/console?{query}"


def _base_url() -> str:
    return (
        os.environ.get("ANT_COLONY_PUBLIC_BASE_URL")
        or os.environ.get("ANT_COLONY_DASHBOARD_BASE_URL")
        or os.environ.get("ANT_COLONY_DOCUMENT_BASE_URL")
        or "http://localhost:18092"
    ).rstrip("/")


def _ttl_seconds() -> int:
    try:
        return int(os.environ.get("ANT_COLONY_ENTRY_LINK_TTL_SECONDS", "86400"))
    except ValueError:
        return 86400


def _matches(text: str, triggers: tuple[str, ...]) -> bool:
    return any(_normalize_text(trigger) in text for trigger in triggers)


def _normalize_text(text: str) -> str:
    return "".join(str(text or "").strip().lower().split())


def _normalize_platform(platform: str) -> str:
    normalized = str(platform or "wecom").strip().lower() or "wecom"
    if normalized in {"wecom", "wecom_bot", "wecom_bot_ws", "企业微信", "企微"}:
        return "wecom"
    if normalized in {"feishu", "lark", "飞书"}:
        return "feishu"
    if normalized in {"dingtalk", "钉钉"}:
        return "dingtalk"
    return normalized


def _build_feishu_entry_card(items: object) -> dict[str, object]:
    elements = []
    for item in items:  # type: ignore[assignment]
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**{item['title']}**\n{item['description']}",
                },
            }
        )
        elements.append(
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "打开"},
                        "type": "primary",
                        "url": item["url"],
                    }
                ],
            }
        )
    return {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": "Ant Colony 入口"}},
        "elements": elements,
    }


def _build_dingtalk_entry_card(items: object) -> dict[str, object]:
    lines = ["### Ant Colony 入口"]
    for item in items:  # type: ignore[assignment]
        lines.append(f"- [{item['title']}]({item['url']})：{item['description']}")
    return {
        "title": "Ant Colony 入口",
        "markdown": "\n".join(lines),
        "single_title": "打开入口",
        "single_url": items[0]["url"] if items else "",  # type: ignore[index]
    }
