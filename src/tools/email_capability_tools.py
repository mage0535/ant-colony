from __future__ import annotations

from typing import Any


def send_email_tool(args: dict[str, Any]) -> str:
    from src.platform import invoke_capability_first

    return invoke_capability_first(
        "mail.send",
        args.get("to", ""),
        args.get("subject", ""),
        args.get("body", ""),
        args.get("cc"),
        empty_message="暂无可用邮件发送能力",
    )


def list_emails_tool(args: dict[str, Any]) -> str:
    from src.platform import invoke_capability

    return invoke_capability(
        "mail.list",
        int(args.get("limit", 10)),
        empty_message="暂无可用邮箱列表能力",
    )


def search_emails_tool(args: dict[str, Any]) -> str:
    from src.platform import invoke_capability

    return invoke_capability(
        "mail.search",
        args.get("query", ""),
        empty_message="暂无可用邮箱搜索能力",
    )


def get_email_tool(args: dict[str, Any]) -> str:
    from src.platform import invoke_capability_first

    return invoke_capability_first(
        "mail.get",
        args.get("uid", ""),
        empty_message="暂无可用邮件详情能力",
    )
