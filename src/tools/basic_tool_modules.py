from __future__ import annotations

import json
from datetime import datetime
from typing import Any


def _context_from_args(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "user_id": str(args.get("user_id") or args.get("from") or ""),
        "platform": str(args.get("_source_provider", "") or args.get("platform", "")),
        "transport": str(args.get("_source_transport", "") or args.get("transport", "")),
        "scope": str(args.get("scope", "")),
        "scope_id": str(args.get("scope_id", "")),
        "source_chat_id": str(args.get("source_chat_id", "")),
        "metadata": {},
    }


def now_tool(args: dict[str, Any]) -> str:
    del args
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def echo_tool(args: dict[str, Any]) -> str:
    return str(args.get("text", ""))


def tushare_tool(args: dict[str, Any]) -> str:
    from src.tools.tushare_mcp import call_tushare

    method = args.get("method", "daily")
    params = {}
    if args.get("code"):
        params["ts_code"] = args["code"]
    if args.get("start"):
        params["start_date"] = args["start"]
    if args.get("end"):
        params["end_date"] = args["end"]
    return call_tushare(method, params)


def humanize_tool(args: dict[str, Any]) -> str:
    from src.tools.humanizer import analyze_text_style, humanize

    text = args.get("text", "")
    if not text:
        return "请提供要处理的文本"
    result = humanize(text)
    style = analyze_text_style(text)
    lines = ["去AI味处理结果:", result]
    if style.get("ai_patterns"):
        lines.append("")
        lines.append("检测到AI模式: " + ", ".join(style["ai_patterns"].keys()))
    return "\n".join(lines)


def ddg_search_tool(args: dict[str, Any]) -> str:
    import urllib.parse
    import urllib.request

    query = args.get("query", "")
    if not query:
        return "请提供搜索关键词"
    try:
        url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(query)}&format=json&no_html=1"
        response = json.loads(urllib.request.urlopen(url, timeout=15).read())
        abstract = response.get("AbstractText", "")
        results = response.get("Results", []) or response.get("RelatedTopics", [])
        lines = [f"DuckDuckGo 搜索结果: {query}"]
        if abstract:
            lines.append(f"摘要: {abstract}")
        for item in results[:8]:
            if isinstance(item, dict) and "Text" in item:
                lines.append(f"  - {item.get('Text', '')}")
            elif isinstance(item, dict) and "Result" in item:
                lines.append(f"  - {item.get('Result', '')}")
        return "\n".join(lines) if len(lines) > 1 else f"未找到关于 '{query}' 的结果"
    except Exception as exc:
        return f"DuckDuckGo 搜索失败: {exc}"


def contact_search_tool(args: dict[str, Any]) -> str:
    from src.platform import invoke_capability

    query = args.get("query", "")
    if not query:
        return "请提供搜索关键词，如姓名、手机号"
    return invoke_capability(
        "contacts.search",
        query,
        context=_context_from_args(args),
        empty_message="未找到匹配的联系人",
    )


def calendar_agenda_tool(args: dict[str, Any]) -> str:
    from src.platform import invoke_capability

    days = int(args.get("days", 7))
    return invoke_capability(
        "calendar.list",
        days,
        context=_context_from_args(args),
        empty_message="未找到日程信息（需配置飞书/钉钉/企微凭证）",
    )
