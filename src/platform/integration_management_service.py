from __future__ import annotations

import time
from typing import Any

from src.store.database import Database


STATUS_ORDER = {"ready": 0, "configured": 0, "degraded": 1, "needs_config": 2, "blocked": 3, "error": 3, "unknown": 4}


def list_integrations(*, platform: str = "wecom", user_id: str = "") -> dict[str, Any]:
    """Return a unified, non-secret view of tools and integrations.

    The center is intentionally read-mostly. Each integration keeps using its
    existing configuration API; this service only aggregates status, test
    actions, and the correct configuration target for admins.
    """

    normalized_platform = (platform or "wecom").strip() or "wecom"
    normalized_user = (user_id or "").strip()
    items: list[dict[str, Any]] = []
    _extend_safe(items, "system:platform", "平台通道", "平台 Bot/应用通道", "bots", _platform_items)
    _extend_safe(
        items,
        "system:enterprise_apps",
        "企业应用连接器",
        "通讯录/日程/审批/会议连接器",
        "runtime",
        lambda: _phase1_items(platform=normalized_platform, user_id=normalized_user),
    )
    _extend_safe(items, "system:models", "模型服务", "LLM 模型配置", "models", _model_items)
    _extend_safe(items, "system:mail", "企业邮箱", "邮箱未读统计与新邮件提醒", "mailAccounts", lambda: _mail_items(platform=normalized_platform))
    _extend_safe(
        items,
        "system:knowledge",
        "知识库",
        "组织/部门/个人知识库",
        "knowledge",
        lambda: _knowledge_items(platform=normalized_platform, user_id=normalized_user),
    )
    _extend_safe(items, "system:ratemin", "现场二开", "业务系统软件通知通道", "ratemin", lambda: _ratemin_items(platform=normalized_platform))
    _extend_safe(items, "system:wecom_mcp", "企业微信 MCP", "文档与待办 MCP", "wecomMcp", _wecom_mcp_items)
    _extend_safe(items, "system:public_data", "公共数据源", "公共数据源", "publicDataSources", _public_data_items)
    _extend_safe(items, "system:search", "联网搜索源", "联网搜索源", "runtime", _search_items)
    summary = _summary(items)
    return {
        "platform": normalized_platform,
        "user_id": normalized_user,
        "checked_at": int(time.time()),
        "summary": summary,
        "items": sorted(items, key=lambda item: (STATUS_ORDER.get(item["status"], 9), item["category"], item["name"])),
    }


def _extend_safe(
    items: list[dict[str, Any]],
    fallback_id: str,
    category: str,
    name: str,
    configure_tab: str,
    loader: Any,
) -> None:
    try:
        items.extend(loader())
    except BaseException as exc:
        items.append(
            _item(
                id=fallback_id,
                category=category,
                name=name,
                status="error",
                summary=f"状态采集失败：{exc}",
                configure_tab=configure_tab,
                testable=False,
                metrics={"error_type": type(exc).__name__},
            )
        )


def test_integration(integration_id: str, *, platform: str = "wecom", user_id: str = "", query: str = "") -> dict[str, Any]:
    normalized_id = (integration_id or "").strip()
    if not normalized_id:
        raise ValueError("缺少集成项目 ID")
    started = time.time()
    try:
        if normalized_id.startswith("public_data:"):
            from src.platform.public_data_service import test_data_source

            kind = normalized_id.split(":", 1)[1]
            result = test_data_source(kind, query=query or _default_public_data_query(kind), params={})
            ok = bool(result.get("ok"))
            detail = str(result.get("result") or result.get("error") or "")
        elif normalized_id.startswith("search:"):
            from src.tools.web_research_service import web_search_aggregate

            source = normalized_id.split(":", 1)[1]
            detail = web_search_aggregate(query or "企业 AI 助手", max_results=5, include_sources=[source])
            ok = "未找到高相关搜索结果" not in detail and "请提供搜索关键词" not in detail
        elif normalized_id == "ratemin:channel":
            from src.platform.ratemin_collector_health import get_ratemin_channel_status

            result = get_ratemin_channel_status(platform=platform)
            ok = result.get("overall_status") == "healthy"
            detail = str(result.get("project_server", {}).get("summary") or result.get("problem_origin") or result)
        elif normalized_id == "knowledge:accessible":
            repo = _knowledge_repo()
            rows = repo.search_accessible(query or "企业 AI 助手", user_id=user_id, limit=5) if user_id else repo.list_accessible(user_id=user_id, limit=5)
            ok = True
            detail = f"知识库可访问，测试返回 {len(rows)} 条。"
        elif normalized_id == "mail:accounts":
            from src.platform.mail_account_service import list_mail_accounts

            accounts = list_mail_accounts(platform=platform).get("accounts", [])
            enabled = [item for item in accounts if item.get("enabled")]
            ok = bool(enabled)
            detail = f"已配置 {len(accounts)} 个邮箱账号，其中启用 {len(enabled)} 个。单邮箱真实读取请在邮箱配置页点击对应账号的测试按钮。"
        elif normalized_id == "models:profiles":
            from src.platform.model_management_service import list_model_profiles

            profiles = list_model_profiles().get("profiles", [])
            default = next((item for item in profiles if item.get("is_default")), None)
            ok = bool(default and default.get("api_key_configured"))
            detail = f"模型配置 {len(profiles)} 个；默认模型：{default.get('model_name') if default else '未设置'}。"
        elif normalized_id.startswith("platform:"):
            from src.platform.activation_service import list_platform_bot_statuses

            target = normalized_id.split(":", 1)[1]
            status = next((item for item in list_platform_bot_statuses() if item.get("platform") == target), {})
            ok = bool(status.get("enabled") and not status.get("missing_keys"))
            detail = str(status.get("next_action") or status)
        elif normalized_id == "wecom_mcp:doc_todo":
            from src.platform.wecom_robot_mcp_provider import get_wecom_robot_mcp_status

            status = get_wecom_robot_mcp_status(discover=True)
            ok = any((status.get(key) or {}).get("configured") for key in ("doc", "todo"))
            detail = _mcp_detail(status)
        elif normalized_id.startswith("enterprise_app:"):
            from src.platform.phase1_readiness_service import collect_phase1_readiness

            key = normalized_id.split(":", 1)[1]
            readiness = collect_phase1_readiness(platform=platform, user_id=user_id)
            item = readiness.get("items", {}).get(key, {})
            ok = item.get("status") in {"ready", "degraded"}
            detail = str(item.get("summary") or item.get("next_action") or item)
        else:
            raise ValueError(f"不支持的集成项目：{normalized_id}")
        return {
            "integration_id": normalized_id,
            "ok": ok,
            "status": "ready" if ok else "needs_config",
            "elapsed_ms": int((time.time() - started) * 1000),
            "result": detail[:5000],
        }
    except Exception as exc:
        return {
            "integration_id": normalized_id,
            "ok": False,
            "status": "error",
            "elapsed_ms": int((time.time() - started) * 1000),
            "result": str(exc),
        }


def _platform_items() -> list[dict[str, Any]]:
    from src.platform.activation_service import list_platform_bot_statuses

    rows = []
    for item in list_platform_bot_statuses():
        status = "ready" if item.get("enabled") and not item.get("missing_keys") else "needs_config"
        if item.get("restart_required"):
            status = "degraded"
        rows.append(
            _item(
                id=f"platform:{item.get('platform')}",
                category="平台通道",
                name=f"{item.get('platform_label') or item.get('platform')} Bot/应用通道",
                status=status,
                summary=item.get("next_action") or "",
                configure_tab="bots",
                testable=True,
                metrics={
                    "configured_keys": item.get("configured_keys", []),
                    "missing_keys": item.get("missing_keys", []),
                    "restart_required": item.get("restart_required", False),
                },
            )
        )
    return rows


def _phase1_items(*, platform: str, user_id: str) -> list[dict[str, Any]]:
    from src.platform.phase1_readiness_service import collect_phase1_readiness

    readiness = collect_phase1_readiness(platform=platform, user_id=user_id)
    rows = []
    for key, item in readiness.get("items", {}).items():
        if key in {"knowledge", "tasks", "mail", "documents"}:
            continue
        rows.append(
            _item(
                id=f"enterprise_app:{key}",
                category="企业应用连接器",
                name=item.get("name") or key,
                status=_normalize_status(item.get("status")),
                summary=item.get("summary") or item.get("next_action") or "",
                configure_tab="runtime",
                testable=True,
                metrics=item.get("metrics", {}),
            )
        )
    return rows


def _model_items() -> list[dict[str, Any]]:
    from src.platform.model_management_service import list_model_profiles

    profiles = list_model_profiles().get("profiles", [])
    enabled = [item for item in profiles if item.get("enabled")]
    default = next((item for item in profiles if item.get("is_default")), None)
    status = "ready" if default and default.get("api_key_configured") else ("degraded" if enabled else "needs_config")
    return [
        _item(
            id="models:profiles",
            category="模型服务",
            name="LLM 模型配置",
            status=status,
            summary=f"已配置 {len(profiles)} 个模型；默认模型：{default.get('model_name') if default else '未设置'}。",
            configure_tab="models",
            testable=True,
            metrics={"profiles": len(profiles), "enabled": len(enabled), "default_profile": default.get("profile_id") if default else ""},
        )
    ]


def _mail_items(*, platform: str) -> list[dict[str, Any]]:
    from src.platform.mail_account_service import list_mail_accounts

    accounts = list_mail_accounts(platform=platform).get("accounts", [])
    enabled = [item for item in accounts if item.get("enabled")]
    password_ready = [item for item in enabled if item.get("password_configured")]
    status = "ready" if password_ready else ("degraded" if accounts else "needs_config")
    return [
        _item(
            id="mail:accounts",
            category="企业邮箱",
            name="邮箱未读统计与新邮件提醒",
            status=status,
            summary=f"已配置 {len(accounts)} 个邮箱账号；启用且有密码/授权码 {len(password_ready)} 个。",
            configure_tab="mailAccounts",
            testable=True,
            metrics={"accounts": len(accounts), "enabled": len(enabled), "password_ready": len(password_ready)},
        )
    ]


def _knowledge_items(*, platform: str, user_id: str) -> list[dict[str, Any]]:
    repo = _knowledge_repo()
    try:
        accessible = repo.list_accessible(user_id=user_id, limit=10) if user_id else repo.list_accessible(user_id="", limit=10)
        count = len(accessible)
        status = "ready" if count else "needs_config"
    except Exception as exc:
        count = 0
        status = "error"
        summary = f"知识库读取失败：{exc}"
    else:
        summary = f"当前身份可读取知识样本 {count} 条；完整权限以组织架构 ACL 为准。"
    return [
        _item(
            id="knowledge:accessible",
            category="知识库",
            name="组织/部门/个人知识库",
            status=status,
            summary=summary,
            configure_tab="knowledge",
            testable=True,
            metrics={"sample_entries": count, "platform": platform},
        )
    ]


def _ratemin_items(*, platform: str) -> list[dict[str, Any]]:
    try:
        from src.platform.ratemin_collector_health import get_ratemin_channel_status

        status = get_ratemin_channel_status(platform=platform)
        normalized = status.get("overall_status") or "unknown"
        summary = status.get("project_server", {}).get("summary") or status.get("problem_origin") or ""
        metrics = {
            "problem_origin": status.get("problem_origin"),
            "auto_recovery_available": status.get("auto_recovery_available"),
        }
    except Exception as exc:
        normalized = "error"
        summary = f"业务系统通道状态读取失败：{exc}"
        metrics = {}
    return [
        _item(
            id="ratemin:channel",
            category="现场二开",
            name="业务系统软件通知通道",
            status=_normalize_status(normalized),
            summary=summary,
            configure_tab="ratemin",
            testable=True,
            metrics=metrics,
        )
    ]


def _wecom_mcp_items() -> list[dict[str, Any]]:
    try:
        from src.platform.wecom_robot_mcp_provider import get_wecom_robot_mcp_status

        status = get_wecom_robot_mcp_status(discover=False)
        doc = status.get("doc") or {}
        todo = status.get("todo") or {}
        configured = bool(doc.get("configured") or todo.get("configured"))
        degraded = any(item.get("configured") and item.get("reachable") is False for item in (doc, todo))
        state = "degraded" if degraded else ("ready" if configured else "needs_config")
        summary = _mcp_detail(status)
    except Exception as exc:
        state = "error"
        summary = f"企业微信文档/待办 MCP 状态读取失败：{exc}"
        status = {}
    return [
        _item(
            id="wecom_mcp:doc_todo",
            category="企业微信 MCP",
            name="文档与待办 MCP",
            status=state,
            summary=summary,
            configure_tab="wecomMcp",
            testable=True,
            metrics=status,
        )
    ]


def _public_data_items() -> list[dict[str, Any]]:
    from src.platform.public_data_service import list_data_source_configs

    rows = []
    for item in list_data_source_configs():
        if item.get("builtin"):
            status = "ready"
        elif item.get("configured") and item.get("enabled", True):
            status = "ready" if item.get("last_test_ok") or not item.get("last_test_at") else "degraded"
        elif item.get("configured"):
            status = "degraded"
        else:
            status = "needs_config"
        rows.append(
            _item(
                id=f"public_data:{item.get('kind')}",
                category="公共数据源",
                name=item.get("label") or item.get("kind"),
                status=status,
                summary=item.get("notes") or item.get("source") or "",
                configure_tab="publicDataSources",
                testable=True,
                metrics={
                    "kind": item.get("kind"),
                    "configured": item.get("configured"),
                    "builtin": item.get("builtin"),
                    "last_test_ok": item.get("last_test_ok"),
                    "last_test_at": item.get("last_test_at"),
                },
            )
        )
    return rows


def _search_items() -> list[dict[str, Any]]:
    from src.tools import web_research_service as web

    source_specs = [
        ("SearXNG", bool(web.ENABLE_SEARXNG and _tcp_available(web.SEARXNG_URL)), web.SEARXNG_URL, False),
        ("Tavily", bool(web.TAVILY_API_KEY), "TAVILY_API_KEY", True),
        ("Firecrawl Search", bool(web.ENABLE_FIRECRAWL and web.FIRECRAWL_API_KEY), "FIRECRAWL_API_KEY", True),
        ("Jina Search Reader", bool(web.ENABLE_JINA), "WEB_RESEARCH_ENABLE_JINA", False),
        ("Brave Search", bool(web.BRAVE_SEARCH_API_KEY), "BRAVE_SEARCH_API_KEY", True),
        ("Exa", bool(web.EXA_API_KEY), "EXA_API_KEY", True),
        ("SerpAPI", bool(web.SERPAPI_API_KEY), "SERPAPI_API_KEY", True),
        ("AnySearch", bool(web.ANYSEARCH_KEY), "ANYSEARCH_KEY", True),
        ("Bing HTML", True, "内置 HTML 兜底", False),
        ("Crossref", True, "公开学术元数据", False),
        ("OpenAlex", True, "公开学术/机构数据", False),
        ("GitHub", True, "公开代码搜索", False),
    ]
    rows = []
    for name, ready, detail, needs_secret in source_specs:
        rows.append(
            _item(
                id=f"search:{name}",
                category="联网搜索源",
                name=name,
                status="ready" if ready else "needs_config",
                summary=f"{'已启用' if ready else '未配置或不可达'}；配置项：{detail}",
                configure_tab="runtime",
                testable=ready,
                metrics={"needs_secret": needs_secret, "detail": detail},
            )
        )
    return rows


def _summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    problem_count = sum(counts.get(key, 0) for key in ("degraded", "needs_config", "blocked", "error"))
    return {
        "total": len(items),
        "ready": counts.get("ready", 0),
        "degraded": counts.get("degraded", 0),
        "needs_config": counts.get("needs_config", 0),
        "blocked": counts.get("blocked", 0),
        "error": counts.get("error", 0),
        "overall_status": "ready" if problem_count == 0 else ("degraded" if counts.get("ready", 0) else "needs_config"),
    }


def _item(
    *,
    id: str,
    category: str,
    name: str,
    status: str,
    summary: str,
    configure_tab: str,
    testable: bool,
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": id,
        "category": category,
        "name": name,
        "status": _normalize_status(status),
        "summary": summary,
        "configure_tab": configure_tab,
        "testable": bool(testable),
        "metrics": metrics or {},
    }


def _normalize_status(status: Any) -> str:
    value = str(status or "unknown").strip().lower()
    if value in {"healthy", "ok", "configured"}:
        return "ready"
    if value in {"ready", "degraded", "needs_config", "blocked", "error"}:
        return value
    if value in {"unhealthy", "failed"}:
        return "blocked"
    return "unknown"


def _default_public_data_query(kind: str) -> str:
    return {
        "weather": "北京天气",
        "air_quality": "北京空气质量",
        "exchange_rate": "USD/CNY",
        "holiday": "CN",
        "flight": "明天去北京的航班",
        "shipment": "货运状态",
        "supply_price": "镍价格",
        "fred": "GDP",
    }.get(kind, "测试")


def _mcp_detail(status: dict[str, Any]) -> str:
    parts = []
    for key in ("doc", "todo"):
        item = status.get(key) or {}
        label = item.get("label") or key
        if item.get("configured"):
            if item.get("reachable") is False:
                parts.append(f"{label}已配置但不可达：{item.get('error') or '未知错误'}")
            else:
                tools = item.get("tools") or []
                parts.append(f"{label}已配置，可用工具 {len(tools)} 个")
        else:
            parts.append(f"{label}未配置")
    return "；".join(parts)


def _knowledge_repo() -> Any:
    from src.knowledge.repository_factory import build_knowledge_repository

    return build_knowledge_repository()


def _tcp_available(url: str) -> bool:
    try:
        from urllib.parse import urlparse
        import socket

        parsed = urlparse(url)
        host = parsed.hostname
        if not host:
            return False
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        with socket.create_connection((host, port), timeout=1.5):
            return True
    except Exception:
        return False
