"""阶段二运行时无副作用检查。"""
from __future__ import annotations

import json
import os
from typing import Any

from src.orchestrator.cron_job import ALLOWED_NO_AGENT_CALLABLES
from src.tools.knowledge_tools import search_knowledge_entries
from src.web.dashboard import app


def build_validation_result() -> dict[str, Any]:
    routes = {route.path for route in app.routes}
    required_routes = {
        "/api/v1/user/assistant-profile",
        "/api/v1/user/subscriptions",
        "/api/v1/admin/phase2/notification-audit",
    }
    guide_titles: list[str] = []
    guide_search_error = ""
    try:
        guide_titles = [
            str(item.metadata.get("title", ""))
            for item in search_knowledge_entries("每日简报 统一搜索 订阅天气", user_id="AdminUser", limit=5)
        ]
    except Exception as exc:
        guide_search_error = str(exc)

    guide_search_ready = any("企业 AI 助手使用总入口" in title for title in guide_titles)
    result = {
        "daily_brief_cron_allowed": "src.platform.daily_brief_service.run_daily_briefs" in ALLOWED_NO_AGENT_CALLABLES,
        "required_routes_ready": required_routes.issubset(routes),
        "guide_search_ready": guide_search_ready,
        "guide_search_titles": guide_titles,
    }
    if guide_search_error:
        result["guide_search_error"] = guide_search_error
        result["diagnostic_hint"] = _guide_search_diagnostic_hint(guide_search_error)
    return result


def _guide_search_diagnostic_hint(error: str) -> str:
    lowered = str(error or "").lower()
    if "10061" in lowered or "connection refused" in lowered or "actively refused" in lowered:
        return "本地未连接知识库/后台服务；请在测试服务器验证，或先启动本地 dashboard 与知识库桥接。"
    if "502" in lowered or "bad gateway" in lowered:
        return "知识库桥接返回 502；优先检查本地代理、NO_PROXY、dashboard 和知识库桥接服务。"
    return "知识库运行态检索失败；请优先在测试服务器复验，再判断是否为本地环境问题。"


def main() -> int:
    result = build_validation_result()
    print(json.dumps(result, ensure_ascii=False))
    allow_empty_guides = os.environ.get("ANT_COLONY_VALIDATE_PHASE2_ALLOW_EMPTY_GUIDES", "").strip().lower() in {"1", "true", "yes"}
    ok = bool(result["daily_brief_cron_allowed"] and result["required_routes_ready"] and (result["guide_search_ready"] or allow_empty_guides))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
