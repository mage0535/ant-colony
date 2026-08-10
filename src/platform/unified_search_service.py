"""按当前用户权限聚合知识库、企业文档、网盘和邮件搜索。"""
from __future__ import annotations

from src.platform import build_capability_context, invoke_capability
from src.tools.knowledge_tools import search_knowledge_tool


def search_workspace(*, user_id: str, platform: str, query: str) -> str:
    keyword = str(query or "").strip()
    if not keyword:
        return "请告诉我需要查找的关键词，例如“统一搜索 设备巡检”。"
    context = build_capability_context(user_id=user_id, platform=platform, scope="personal")
    sources = (
        ("知识库", lambda: search_knowledge_tool({"query": keyword, "user_id": user_id, "platform": platform})),
        ("企业文档", lambda: invoke_capability("docs.search", keyword, context=context, empty_message="")),
        ("网盘", lambda: invoke_capability("drive.search", keyword, context=context, empty_message="")),
        ("邮件", lambda: invoke_capability("mail.search", keyword, context=context, empty_message="")),
    )
    sections: list[str] = []
    for label, loader in sources:
        try:
            content = str(loader() or "").strip()
        except Exception:
            content = ""
        if content and not content.startswith("未找到"):
            sections.append(f"【{label}】\n{content[:1200]}")
    if not sections:
        return f"在你当前有权限访问的知识库、企业文档、网盘和邮件中，未找到与“{keyword}”相关的结果。"
    return f"【统一检索】{keyword}\n以下结果均已按你当前权限筛选：\n\n" + "\n\n".join(sections)
