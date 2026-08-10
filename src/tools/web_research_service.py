from __future__ import annotations

import hashlib
import html
import json
import os
import random
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from typing import Any


DEFAULT_USER_AGENT = os.environ.get("WEB_RESEARCH_USER_AGENT", "Ant-Colony-AI-Assistant/1.0")
SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://127.0.0.1:8899").rstrip("/")
ANYSEARCH_URL = os.environ.get("ANYSEARCH_URL", "https://api.anysearch.com/mcp")
ANYSEARCH_KEY = os.environ.get("ANYSEARCH_KEY", "")
BRAVE_SEARCH_API_KEY = os.environ.get("BRAVE_SEARCH_API_KEY", "")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
EXA_API_KEY = os.environ.get("EXA_API_KEY", "")
SERPAPI_API_KEY = os.environ.get("SERPAPI_API_KEY", "")
FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "")
FIRECRAWL_API_URL = os.environ.get("FIRECRAWL_API_URL", "https://api.firecrawl.dev/v2").rstrip("/")
JINA_API_KEY = os.environ.get("JINA_API_KEY", "")
ENABLE_JINA = os.environ.get("WEB_RESEARCH_ENABLE_JINA", "1").lower() not in {"0", "false", "no"}
ENABLE_SEARXNG = os.environ.get("WEB_RESEARCH_ENABLE_SEARXNG", "1").lower() not in {"0", "false", "no"}
ENABLE_CRAWL4AI = os.environ.get("WEB_RESEARCH_ENABLE_CRAWL4AI", "1").lower() not in {"0", "false", "no"}
ENABLE_FIRECRAWL = os.environ.get("WEB_RESEARCH_ENABLE_FIRECRAWL", "1").lower() not in {"0", "false", "no"}
ENABLE_PLAYWRIGHT = os.environ.get("WEB_RESEARCH_ENABLE_PLAYWRIGHT", "1").lower() not in {"0", "false", "no"}
ENABLE_SLOW_SEARCH_SOURCES = os.environ.get("WEB_RESEARCH_ENABLE_SLOW_SOURCES", "0").lower() in {"1", "true", "yes"}
SEARCH_MAX_WORKERS = max(1, int(os.environ.get("WEB_RESEARCH_MAX_WORKERS", "8")))
DEFAULT_READ_BACKEND = os.environ.get("WEB_RESEARCH_READ_BACKEND", "auto").lower()
DEFAULT_RESEARCH_READ_TOP = int(os.environ.get("WEB_RESEARCH_DEFAULT_READ_TOP", "1"))
READ_TIMEOUT_SECONDS = float(os.environ.get("WEB_RESEARCH_READ_TIMEOUT_SECONDS", "18"))
FETCH_TIMEOUT_SECONDS = float(os.environ.get("WEB_RESEARCH_FETCH_TIMEOUT_SECONDS", "10"))
CACHE_DB = os.environ.get("WEB_RESEARCH_CACHE_DB", "data/web-research-cache.db")
PAGE_CACHE_DIR = os.environ.get("WEB_RESEARCH_PAGE_CACHE_DIR", "data/web-search-page-cache")
PAGE_CACHE_TTL_SECONDS = int(os.environ.get("WEB_RESEARCH_PAGE_CACHE_TTL_SECONDS", "3600"))
RESPECT_ROBOTS = os.environ.get("WEB_RESEARCH_RESPECT_ROBOTS", "1").lower() not in {"0", "false", "no"}
MIN_HOST_INTERVAL = float(os.environ.get("WEB_RESEARCH_MIN_HOST_INTERVAL", "1.0"))

_LAST_HOST_ACCESS: dict[str, float] = {}


def _public_dashboard_base_url() -> str:
    for key in (
        "ANT_COLONY_PUBLIC_BASE_URL",
        "ANT_COLONY_DASHBOARD_BASE_URL",
        "ANT_COLONY_DOCUMENT_BASE_URL",
    ):
        value = os.environ.get(key, "").strip()
        if value:
            return value.rstrip("/")
    return "http://localhost:18092"


def _build_web_search_more_url(query: str, page: int, page_size: int) -> str:
    params = urllib.parse.urlencode(
        {
            "q": query,
            "page": max(1, int(page or 1)),
            "page_size": max(1, min(int(page_size or 20), 20)),
        }
    )
    return f"{_public_dashboard_base_url()}/api/v1/web-search/more?{params}"


def _build_web_search_page_url(query: str, page: int, page_size: int) -> str:
    return _build_web_search_more_url(query, page, page_size)


def _page_cache_path(query: str) -> str:
    key = hashlib.sha256(str(query or "").strip().encode("utf-8")).hexdigest()
    return os.path.join(PAGE_CACHE_DIR, f"{key}.json")


def _write_search_page_cache(query: str, selected: list[dict[str, str]], diagnostics: list[str]) -> None:
    try:
        os.makedirs(PAGE_CACHE_DIR, exist_ok=True)
        payload = {
            "query": str(query or "").strip(),
            "created_at": time.time(),
            "selected": selected,
            "diagnostics": diagnostics,
        }
        with open(_page_cache_path(query), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
    except Exception:
        return


def _read_search_page_cache(query: str) -> tuple[list[dict[str, str]], list[str]] | None:
    try:
        with open(_page_cache_path(query), "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        if time.time() - float(payload.get("created_at") or 0) > PAGE_CACHE_TTL_SECONDS:
            return None
        selected = payload.get("selected")
        diagnostics = payload.get("diagnostics") or []
        if not isinstance(selected, list):
            return None
        return selected, diagnostics if isinstance(diagnostics, list) else []
    except Exception:
        return None


def web_search(query: str, *, max_results: int = 8, freshness: str = "", domains: list[str] | None = None) -> str:
    query = str(query or "").strip()
    if not query:
        return "请提供搜索关键词。"
    max_results = max(1, min(int(max_results or 8), 20))
    if domains:
        domain_query = " OR ".join(f"site:{d}" for d in domains if d)
        if domain_query:
            query = f"({domain_query}) {query}"

    results = _search_searxng(query, max_results, freshness=freshness)
    source = "SearXNG"
    if not results:
        results = _search_duckduckgo_instant(query, max_results)
        source = "DuckDuckGo Instant Answer"
    if not results:
        results = _search_duckduckgo_html(query, max_results)
        source = "DuckDuckGo HTML"
    if not results and ENABLE_JINA:
        results = _search_jina_bing(query, max_results)
        source = "Jina Bing Reader"
    if not results:
        results = _search_bing_html(query, max_results)
        source = "Bing HTML"
    if not results and ENABLE_JINA:
        results = _search_jina(query, max_results)
        source = "Jina Search Reader"
    if not results:
        results = _search_wikipedia(query, max_results)
        source = "Wikipedia"
    if not results and ANYSEARCH_KEY:
        results = _search_anysearch(query, max_results)
        source = "AnySearch"
    if not results:
        return (
            f"未找到可用搜索结果：{query}\n"
            "建议管理员配置自托管 SearXNG（SEARXNG_URL），或配置 JINA_API_KEY / ANYSEARCH_KEY 作为外部回退。"
        )
    return _format_search_results(query, results[:max_results], source)


def web_search_aggregate(
    query: str,
    *,
    max_results: int = 10,
    freshness: str = "",
    domains: list[str] | None = None,
    include_sources: list[str] | None = None,
) -> str:
    query = str(query or "").strip()
    if not query:
        return "请提供搜索关键词。"
    max_results = max(1, min(int(max_results or 10), 30))
    search_query = query
    if domains:
        domain_query = " OR ".join(f"site:{d}" for d in domains if d)
        if domain_query:
            search_query = f"({domain_query}) {query}"
    rows, diagnostics = _aggregate_search_results(
        search_query,
        max_results=max_results,
        freshness=freshness,
        include_sources=include_sources,
    )
    if not rows and include_sources:
        retry_rows, retry_diagnostics = _aggregate_search_results(
            search_query,
            max_results=max_results,
            freshness=freshness,
            include_sources=[],
        )
        if retry_rows:
            diagnostics.append("Source fallback: 指定来源无高相关结果，已自动改用全部可用搜索来源")
            diagnostics.extend(retry_diagnostics)
            rows = retry_rows
    if not rows:
        diag = "\n".join(f"- {item}" for item in diagnostics if item)
        return f"未找到高相关搜索结果：{query}\n已尝试来源：\n{diag or '- 无可用来源'}"
    selected = _select_diverse_search_results(query, rows, max_results)
    lines = [f"多源搜索：{query}", f"命中 {len(selected)} 条高相关结果。"]
    sources = "、".join(sorted({row.get("_source", "") for row in selected if row.get("_source")}))
    if sources:
        lines.append(f"可用来源：{sources}")
    lines.extend(["", "推荐阅读顺序："])
    for idx, item in enumerate(selected[:20], start=1):
        lines.append(f"{idx}. {item.get('title') or '无标题'}（{item.get('_source', '未知来源')}）")
    grouped: dict[str, list[dict[str, str]]] = {}
    for item in selected:
        grouped.setdefault(_source_group_label(item.get("_source", "")), []).append(item)
    for group, items in grouped.items():
        lines.extend(["", f"【{group}】"])
        for idx, item in enumerate(items, start=1):
            lines.append(f"{idx}. {item.get('title') or '无标题'}")
            if item.get("url"):
                lines.append(f"   {item['url']}")
            if item.get("snippet"):
                lines.append(f"   摘要：{item['snippet'][:300]}")
            if item.get("_source"):
                lines.append(f"   来源：{item['_source']}")
    lines.extend([
        "",
        "给 AI 的展示建议：先说明最相关的 3-5 条资料，再按“正式论文/代码工具/社区讨论/网页结果”分组；不要把低相关结果混入结论。",
    ])
    if diagnostics:
        lines.extend(["", "来源诊断："])
        lines.extend(f"- {item}" for item in diagnostics)
    return "\n".join(lines)[:20000]


def web_search_aggregate_page(
    query: str,
    *,
    page: int = 1,
    page_size: int = 20,
    max_total: int = 60,
    freshness: str = "",
    domains: list[str] | None = None,
    include_sources: list[str] | None = None,
) -> str:
    query = str(query or "").strip()
    if not query:
        return "请提供搜索关键词。"
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 20), 20))
    max_total = max(page * page_size, min(int(max_total or 60), 80))
    search_query = query
    if domains:
        domain_query = " OR ".join(f"site:{d}" for d in domains if d)
        if domain_query:
            search_query = f"({domain_query}) {query}"
    if page > 1:
        cached = _read_search_page_cache(search_query)
        if cached:
            selected, diagnostics = cached
            start = (page - 1) * page_size
            page_items = selected[start:start + page_size]
            if not page_items:
                return f"没有更多高相关搜索结果：{query}\n当前已到第 {page} 页。"
            return _format_aggregate_page_results(
                query,
                page_items,
                diagnostics,
                total_count=len(selected),
                page=page,
                page_size=page_size,
                has_more=(start + page_size) < len(selected),
                start_index=start + 1,
            )
        return (
            f"更多结果缓存已过期或服务刚重启：{query}\n"
            "请回到企业微信回复“查看更多”，或重新发起一次“上网查找……”检索。"
        )
    rows, diagnostics = _aggregate_search_results(
        search_query,
        max_results=max_total,
        freshness=freshness,
        include_sources=include_sources,
    )
    if not rows and include_sources:
        retry_rows, retry_diagnostics = _aggregate_search_results(
            search_query,
            max_results=max_total,
            freshness=freshness,
            include_sources=[],
        )
        if retry_rows:
            diagnostics.append("Source fallback: 指定来源无高相关结果，已自动改用全部可用搜索来源")
            diagnostics.extend(retry_diagnostics)
            rows = retry_rows
    if not rows:
        diag = "\n".join(f"- {item}" for item in diagnostics if item)
        return f"未找到高相关搜索结果：{query}\n已尝试来源：\n{diag or '- 无可用来源'}"
    selected = _select_diverse_search_results(query, rows, max_total)
    _write_search_page_cache(search_query, selected, diagnostics)
    start = (page - 1) * page_size
    page_items = selected[start:start + page_size]
    if not page_items:
        return f"没有更多高相关搜索结果：{query}\n当前已到第 {page} 页。"
    return _format_aggregate_page_results(
        query,
        page_items,
        diagnostics,
        total_count=len(selected),
        page=page,
        page_size=page_size,
        has_more=(start + page_size) < len(selected),
        start_index=start + 1,
    )


def web_search_aggregate_page_cached(query: str, *, page: int = 1, page_size: int = 20) -> str:
    query = str(query or "").strip()
    if not query:
        return "请提供搜索关键词。"
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 20), 20))
    cached = _read_search_page_cache(query)
    if not cached:
        return (
            f"搜索结果缓存已过期或服务刚重启：{query}\n"
            "请回到企业微信回复“查看更多”，或重新发起一次“上网查找……”检索。"
        )
    selected, diagnostics = cached
    start = (page - 1) * page_size
    page_items = selected[start:start + page_size]
    if not page_items:
        return f"没有更多高相关搜索结果：{query}\n当前已到第 {page} 页。"
    return _format_aggregate_page_results(
        query,
        page_items,
        diagnostics,
        total_count=len(selected),
        page=page,
        page_size=page_size,
        has_more=(start + page_size) < len(selected),
        start_index=start + 1,
    )


def _format_aggregate_page_results(
    query: str,
    selected: list[dict[str, str]],
    diagnostics: list[str],
    *,
    total_count: int,
    page: int,
    page_size: int,
    has_more: bool,
    start_index: int,
) -> str:
    lines = [f"多源搜索：{query}", f"命中 {total_count} 条高相关结果，当前显示第 {page} 页 {len(selected)} 条。"]
    sources = "、".join(sorted({row.get("_source", "") for row in selected if row.get("_source")}))
    if sources:
        lines.append(f"可用来源：{sources}")
    page_url = _build_web_search_page_url(query, page, page_size)
    lines.extend(["", f"打开网页查看本页结果：{page_url}"])
    if has_more:
        more_url = _build_web_search_more_url(query, page + 1, page_size)
        lines.extend(
            [
                "",
                f"查看更多结果（第 {page + 1} 页）：{more_url}",
                "也可以回复“查看更多”或“下一页”继续查看。",
            ]
        )
    lines.extend(["", "推荐阅读顺序："])
    for offset, item in enumerate(selected[:page_size], start=0):
        idx = start_index + offset
        lines.append(f"{idx}. {item.get('title') or '无标题'}（{item.get('_source', '未知来源')}）")
        if item.get("url"):
            lines.append(f"   {item['url']}")
    grouped: dict[str, list[tuple[int, dict[str, str]]]] = {}
    for offset, item in enumerate(selected, start=0):
        grouped.setdefault(_source_group_label(item.get("_source", "")), []).append((start_index + offset, item))
    for group, items in grouped.items():
        lines.extend(["", f"【{group}】"])
        for idx, item in items:
            lines.append(f"{idx}. {item.get('title') or '无标题'}")
            if item.get("url"):
                lines.append(f"   {item['url']}")
            if item.get("snippet"):
                lines.append(f"   摘要：{item['snippet'][:300]}")
            if item.get("_source"):
                lines.append(f"   来源：{item['_source']}")
    if has_more:
        lines.extend(["", "还有更多结果，更多结果链接见上方。"])
    else:
        lines.extend(["", "已显示当前检索到的全部高相关结果。"])
    if diagnostics:
        lines.extend(["", "来源诊断："])
        lines.extend(f"- {item}" for item in diagnostics)
    return "\n".join(lines)[:20000]


def web_ppt_search(query: str, *, max_results: int = 8) -> str:
    query = str(query or "").strip()
    if not query:
        return "请提供要查找的 PPT 主题。"
    max_results = max(1, min(int(max_results or 8), 20))
    variants = _ppt_query_variants(query)
    source_calls = [
        ("Tavily", lambda q: _search_tavily_api(q, max_results)),
        ("Firecrawl Search", lambda q: _search_firecrawl_api(q, max_results)),
        ("Exa", lambda q: _search_exa_api(q, max_results)),
        ("Brave Search", lambda q: _search_brave_api(q, max_results)),
        ("SerpAPI", lambda q: _search_serpapi(q, max_results)),
        ("SearXNG", lambda q: _search_searxng(q, max_results)),
        ("Bing HTML", lambda q: _search_bing_html(q, max_results)),
        ("AnySearch", lambda q: _search_anysearch(q, max_results) if ANYSEARCH_KEY else []),
    ]
    collected: list[dict[str, str]] = []
    diagnostics: list[str] = []
    for source, call in source_calls:
        source_count = 0
        source_errors: list[str] = []
        for variant in variants[:4]:
            try:
                rows = call(variant)
            except Exception as exc:
                source_errors.append(str(exc))
                continue
            source_count += len(rows or [])
            for row in rows or []:
                item = dict(row)
                item["_source"] = source
                item["_query"] = variant
                collected.append(item)
        if source_count:
            diagnostics.append(f"{source}: {source_count}")
        elif source_errors:
            diagnostics.append(f"{source}: error {source_errors[0]}")
        else:
            diagnostics.append(f"{source}: 0")
    deduped = _dedupe_search_results(collected)
    relevant = _filter_relevant_search_results(query, deduped)
    ppt_like = [item for item in relevant if _is_ppt_like_result(item)]
    ppt_topic_relevant = [item for item in ppt_like if _is_ppt_topic_relevant(query, item)]
    selected = _rank_search_results(query, ppt_topic_relevant)[:max_results]
    fallback_selected: list[dict[str, str]] = []
    if not selected:
        fallback_pool = _filter_ppt_fallback_pool(query, relevant or deduped)
        if not fallback_pool and relevant:
            fallback_pool = _filter_ppt_fallback_pool(query, deduped)
        fallback_selected = _select_diverse_search_results(query, fallback_pool, max_results)
    if deduped and len(relevant) != len(deduped):
        diagnostics.append(f"Relevance filter: kept {len(relevant)}/{len(deduped)}")
    if relevant and ppt_like and len(ppt_like) != len(relevant):
        diagnostics.append(f"PPT filter: kept {len(ppt_like)}/{len(relevant)}")
    if ppt_like and len(ppt_topic_relevant) != len(ppt_like):
        diagnostics.append(f"PPT topic filter: kept {len(ppt_topic_relevant)}/{len(ppt_like)}")
    if not selected and fallback_selected:
        diagnostics.append(f"Fallback direct results: showing {len(fallback_selected)}/{len(deduped)}")
        lines = [
            f"未找到可确认的高相关 PPT/PPTX/课件文件：{query}",
            "以下是继续保留的直接搜索结果，可打开查看；其中可能包含网页、PDF、行业文章或可用于整理 PPT 的资料线索：",
            "",
        ]
        for idx, item in enumerate(fallback_selected, start=1):
            lines.append(f"{idx}. {item.get('title') or '无标题'}")
            if item.get("url"):
                lines.append(f"   {item['url']}")
            if item.get("snippet"):
                lines.append(f"   摘要：{item['snippet'][:300]}")
            if item.get("_source"):
                lines.append(f"   来源：{item['_source']}")
        if diagnostics:
            lines.extend(["", "来源诊断："])
            lines.extend(f"- {item}" for item in diagnostics)
        return "\n".join(lines)[:12000]
    if not selected:
        diag = "\n".join(f"- {item}" for item in diagnostics if item)
        return (
            f"未找到明确高相关 PPT/PPTX/课件结果：{query}\n"
            "已优先尝试 Tavily、Firecrawl Search、Exa、Brave、SerpAPI、SearXNG、Bing、AnySearch 等来源。\n"
            "如果企业网盘或知识库中有内部课件，建议同步到企业知识库后再检索。\n"
            f"来源诊断：\n{diag or '- 无可用来源'}"
        )
    lines = [
        f"专项 PPT 检索：{query}",
        f"命中 {len(selected)} 条结果。",
        "",
        "结果说明：优先展示标题、摘要或链接中明确包含 PPT/PPTX/课件/幻灯片的条目；如果没有明确 PPT 文件，会只保留高相关网页并说明诊断。",
        "",
    ]
    for idx, item in enumerate(selected, start=1):
        lines.append(f"{idx}. {item.get('title') or '无标题'}")
        if item.get("url"):
            lines.append(f"   {item['url']}")
        if item.get("snippet"):
            lines.append(f"   摘要：{item['snippet'][:300]}")
        if item.get("_source"):
            lines.append(f"   来源：{item['_source']}")
    if diagnostics:
        lines.extend(["", "来源诊断："])
        lines.extend(f"- {item}" for item in diagnostics)
    return "\n".join(lines)[:12000]


def web_read(url: str, *, max_chars: int = 6000, render: bool = False, backend: str = "auto") -> str:
    normalized = _normalize_url(url)
    if not normalized:
        return "请提供 http 或 https 网页地址。"
    selected_backend = _select_read_backend(render=render, backend=backend)
    cache_key = f"{normalized}|backend={selected_backend}|render={int(render)}"
    cached = _cache_get("read", cache_key, max_age=int(os.environ.get("WEB_RESEARCH_CACHE_TTL", "3600")))
    if cached:
        return cached[:max_chars]
    if not _allowed_by_robots(normalized):
        return f"根据 robots.txt 规则，当前不抓取该页面：{normalized}"
    try:
        raw = _fetch_by_backend(normalized, selected_backend)
        text = _extract_readable_text(raw, normalized)
        result = f"网页正文：{normalized}\n读取方式：{selected_backend}\n\n{text[:max_chars]}"
        _cache_set("read", cache_key, result)
        return result
    except Exception as exc:
        if selected_backend not in {"static", "jina_reader"}:
            try:
                raw = _fetch_text(normalized)
                text = _extract_readable_text(raw, normalized)
                result = f"网页正文：{normalized}\n读取方式：static fallback\n\n{text[:max_chars]}"
                _cache_set("read", cache_key, result)
                return result
            except Exception:
                pass
        return f"网页读取失败：{normalized}\n读取方式：{selected_backend}\n原因：{exc}"


def web_research(query: str, *, max_results: int = 5, read_top: int | None = None, freshness: str = "") -> str:
    query = str(query or "").strip()
    if not query:
        return "请提供调研主题。"
    if read_top is None:
        read_top = DEFAULT_RESEARCH_READ_TOP
    read_top = max(0, min(int(read_top or 0), 2))
    results, diagnostics = _aggregate_search_results(query, max_results=max_results, freshness=freshness)
    if not results:
        diag = "\n".join(f"- {item}" for item in diagnostics if item)
        return f"未找到高相关搜索结果：{query}\n已尝试来源：\n{diag or '- 无可用来源'}"

    lines = [f"综合检索：{query}", "", "搜索结果："]
    for idx, item in enumerate(results[:max_results], start=1):
        lines.append(f"{idx}. {item.get('title') or '无标题'}")
        if item.get("url"):
            lines.append(f"   {item['url']}")
        if item.get("snippet"):
            lines.append(f"   {item['snippet'][:220]}")
        if item.get("_source"):
            lines.append(f"   来源：{item['_source']}")

    lines.extend(["", "重点页面摘取："])
    read_count = 0
    for item in results:
        url = item.get("url", "")
        if not url or read_count >= read_top:
            continue
        if _is_low_quality_research_page(url):
            continue
        if _is_metadata_only_page(url):
            continue
        content = web_read(url, max_chars=1800)
        if content.startswith("网页正文："):
            read_count += 1
            excerpt = content.split("\n\n", 1)[-1].strip()
            lines.append(f"\n[{read_count}] {item.get('title') or url}")
            lines.append(excerpt[:1000])
    if read_count == 0:
        lines.append("未能读取搜索结果正文，已保留搜索摘要。")
    if diagnostics:
        lines.extend(["", "来源诊断："])
        lines.extend(f"- {item}" for item in diagnostics)
    return "\n".join(lines)[:10000]


def discover_public_sources(topic_or_url: str, *, max_items: int = 12) -> str:
    value = str(topic_or_url or "").strip()
    if not value:
        return "请提供网站地址或主题关键词。"
    url = _normalize_url(value)
    if url:
        found = _discover_from_site(url, max_items=max_items)
        if not found:
            return f"未在该站点发现 RSS/Atom 或 sitemap：{url}"
        lines = [f"发现公开信息源：{url}"]
        for item in found[:max_items]:
            lines.append(f"- {item['type']}: {item['url']}")
        return "\n".join(lines)
    return web_search(f"{value} RSS OR sitemap OR API OR dataset", max_results=max_items)


def random_public_info(topic: str = "", *, count: int = 3) -> str:
    topic = str(topic or "").strip()
    count = max(1, min(int(count or 3), 10))
    if topic:
        return web_search(topic, max_results=count)
    items = []
    for _ in range(count):
        try:
            title = _fetch_text("https://en.wikipedia.org/api/rest_v1/page/random/title")
            data = json.loads(title)
            page = data.get("items", [{}])[0].get("title", "")
            if page:
                summary = _fetch_text(f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(page)}")
                parsed = json.loads(summary)
                items.append(f"- {parsed.get('title', page)}：{parsed.get('extract', '')[:300]}")
        except Exception:
            break
    if items:
        return "随机公共知识：\n" + "\n".join(items)
    fallback_topics = [
        "生产管理 best practices",
        "enterprise AI assistant open source",
        "knowledge management workflow",
        "manufacturing safety management",
        "office automation tools",
        "public dataset API",
    ]
    return "随机公共信息发现：\n" + web_search(random.choice(fallback_topics), max_results=count)


def web_research_health() -> str:
    checks: list[tuple[str, bool, str]] = []
    checks.append(("SearXNG", _tcp_available(SEARXNG_URL), SEARXNG_URL))
    checks.append(("Jina Reader", ENABLE_JINA, "enabled" if ENABLE_JINA else "disabled"))
    checks.append(("AnySearch", bool(ANYSEARCH_KEY), "configured" if ANYSEARCH_KEY else "not configured"))
    checks.append(("Tavily", bool(TAVILY_API_KEY), "configured" if TAVILY_API_KEY else "not configured"))
    checks.append(("Exa", bool(EXA_API_KEY), "configured" if EXA_API_KEY else "not configured"))
    checks.append(("Brave Search", bool(BRAVE_SEARCH_API_KEY), "configured" if BRAVE_SEARCH_API_KEY else "not configured"))
    checks.append(("SerpAPI", bool(SERPAPI_API_KEY), "configured" if SERPAPI_API_KEY else "not configured"))
    checks.append(("robots.txt", RESPECT_ROBOTS, "respect enabled" if RESPECT_ROBOTS else "respect disabled"))
    checks.append(("cache", _cache_health(), CACHE_DB))
    checks.append(("trafilatura", _module_available("trafilatura"), "readable text extraction"))
    checks.append(("Firecrawl Search/Read", ENABLE_FIRECRAWL and bool(FIRECRAWL_API_KEY), "configured" if FIRECRAWL_API_KEY else "not configured"))
    checks.append(("Crawl4AI", ENABLE_CRAWL4AI and _module_available("crawl4ai"), "local crawl backend"))
    checks.append(("Playwright", ENABLE_PLAYWRIGHT and _module_available("playwright.sync_api"), "dynamic page rendering"))
    browser_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or os.path.expanduser("~/.cache/ms-playwright")
    browser_ok = os.path.isdir(browser_path) and bool(os.listdir(browser_path)) if os.path.isdir(browser_path) else False
    checks.append(("Playwright browsers", browser_ok, browser_path))
    lines = ["互联网搜索和网页读取能力状态："]
    for name, ok, detail in checks:
        lines.append(f"- {name}: {'可用' if ok else '不可用'} ({detail})")
    lines.extend(
        [
            "",
            "建议：",
            "- 生产优先配置自托管 SearXNG 作为无 key 保底搜索，再按预算配置 Tavily / Firecrawl Search / Exa / Brave Search / SerpAPI 增强召回。",
            "- Firecrawl / Crawl4AI / Playwright 只用于公开或已授权页面读取，不用于绕过登录、验证码、付费墙或访问控制。",
            "- 如果动态网页读取失败，先用 backend=static、backend=firecrawl 或 backend=crawl4ai 降级，再检查浏览器依赖。",
        ]
    )
    return "\n".join(lines)


def _aggregate_search_results(
    query: str,
    *,
    max_results: int,
    freshness: str = "",
    include_sources: list[str] | None = None,
) -> tuple[list[dict[str, str]], list[str]]:
    wanted = {item.lower() for item in include_sources or [] if item}
    diagnostics: list[str] = []
    collected: list[dict[str, str]] = []

    def enabled(name: str) -> bool:
        return not wanted or name.lower() in wanted

    source_calls = [
        ("Crossref", lambda q, limit: _search_crossref(q, limit), "variants"),
        ("OpenAlex", lambda q, limit: _search_openalex(q, limit), "variants"),
        ("arXiv", lambda q, limit: _search_arxiv(q, limit), "variants"),
        ("Tavily", lambda q, limit: _search_tavily_api(q, limit), "variants"),
        ("Firecrawl Search", lambda q, limit: _search_firecrawl_api(q, limit), "variants"),
        ("Exa", lambda q, limit: _search_exa_api(q, limit), "variants"),
        ("Brave Search", lambda q, limit: _search_brave_api(q, limit), "variants"),
        ("SerpAPI", lambda q, limit: _search_serpapi(q, limit), "variants"),
        ("GitHub", lambda q, limit: _search_github(q, limit), "original"),
        ("StackExchange", lambda q, limit: _search_stackexchange(q, limit), "original"),
        ("Hacker News", lambda q, limit: _search_hackernews(q, limit), "original"),
        ("Bing HTML", lambda q, limit: _search_bing_html(q, limit), "variants"),
        ("AnySearch", lambda q, limit: _search_anysearch(q, limit) if ANYSEARCH_KEY else [], "variants"),
    ]
    if ENABLE_SEARXNG or enabled("SearXNG"):
        source_calls.insert(0, ("SearXNG", lambda q, limit: _search_searxng(q, limit, freshness=freshness), "original"))
    if ENABLE_SLOW_SEARCH_SOURCES:
        source_calls.extend([
            ("DuckDuckGo Instant Answer", lambda q, limit: _search_duckduckgo_instant(q, limit), "original"),
            ("DuckDuckGo HTML", lambda q, limit: _search_duckduckgo_html(q, limit), "original"),
            ("Jina Bing Reader", lambda q, limit: _search_jina_bing(q, limit) if ENABLE_JINA else [], "original"),
            ("Jina Search Reader", lambda q, limit: _search_jina(q, limit) if ENABLE_JINA else [], "original"),
            ("Wikipedia", lambda q, limit: _search_wikipedia(q, limit), "original"),
        ])
    variants = _query_variants(query)
    source_order: list[str] = []
    futures: dict[Any, str] = {}
    source_results: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=SEARCH_MAX_WORKERS) as executor:
        for source, call, variant_mode in source_calls:
            if not enabled(source):
                continue
            source_order.append(source)
            call_variants = _variants_for_source(query, source, variants, variant_mode)
            per_call_limit = _per_source_call_limit(source, max_results, len(call_variants))
            futures[executor.submit(_run_source_search_calls, source, call, call_variants, per_call_limit)] = source
        for future in as_completed(futures):
            source = futures[future]
            rows, source_count, source_errors = future.result()
            source_results[source] = {"count": source_count, "errors": source_errors}
            for item in rows:
                collected.append(item)
    for source in source_order:
        if not enabled(source):
            continue
        source_count = int(source_results.get(source, {}).get("count", 0))
        source_errors = list(source_results.get(source, {}).get("errors", []))
        if source_count:
            diagnostics.append(f"{source}: {source_count}")
        elif source_errors:
            diagnostics.append(f"{source}: error {source_errors[0]}")
        else:
            diagnostics.append(f"{source}: 0")
    deduped = _dedupe_search_results(collected)
    relevant = _filter_relevant_search_results(query, deduped)
    if deduped and len(relevant) != len(deduped):
        diagnostics.append(f"Relevance filter: kept {len(relevant)}/{len(deduped)}")
    return _select_diverse_search_results(query, relevant, max_results), diagnostics


def _variants_for_source(query: str, source: str, variants: list[str], variant_mode: str) -> list[str]:
    if variant_mode != "variants":
        return variants[:1]
    if not _is_heterostructured_metal_query(query):
        return variants
    normalized_source = str(source or "").lower()
    if normalized_source == "crossref":
        priority = {
            "heterostructured metals processing manufacturing",
            "heterostructured metallic materials",
            "heterostructured metals review",
            "heterostructured metals mechanical behavior",
            "heterostructured metals interfaces properties",
            "nanostructured heterostructured metals",
            "heterostructured metallic materials design manufacture",
            "nanostructured metals plastic deformation",
            "bulk nanostructured metals alloys severe plastic deformation",
        }
        selected = [item for item in variants if item in priority]
        if variants:
            selected.insert(0, variants[0])
        return selected[:10]
    if normalized_source in {"openalex", "arxiv"}:
        return variants[:8]
    if normalized_source in {"bing html", "tavily", "firecrawl search"}:
        return variants[:8]
    return variants[:4]


def _run_source_search_calls(
    source: str,
    call: Any,
    variants: list[str],
    per_call_limit: int,
) -> tuple[list[dict[str, str]], int, list[str]]:
    collected: list[dict[str, str]] = []
    source_count = 0
    source_errors: list[str] = []
    for variant in variants:
        try:
            rows = call(variant, per_call_limit)
        except Exception as exc:
            source_errors.append(str(exc))
            continue
        source_count += len(rows or [])
        for row in rows or []:
            item = dict(row)
            item["_source"] = source
            item["_query"] = variant
            collected.append(item)
    return collected, source_count, source_errors


def _per_source_call_limit(source: str, max_results: int, variant_count: int) -> int:
    normalized_source = str(source or "").lower()
    if normalized_source in {"crossref", "openalex", "arxiv"}:
        if normalized_source == "crossref":
            return max(8, min(30, max_results))
        return max(8, min(20, max_results))
    if variant_count > 1:
        return max(5, min(12, max_results))
    return max(5, min(max_results, 20))


def _dedupe_search_results(results: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in results:
        url = str(item.get("url") or "").strip()
        if url and not _normalize_url(url):
            continue
        fingerprint = _result_fingerprint(item)
        if not fingerprint or fingerprint in seen:
            continue
        seen.add(fingerprint)
        deduped.append(item)
    return deduped


def _source_group_label(source: str) -> str:
    normalized = str(source or "").lower()
    if normalized in {"crossref", "openalex", "arxiv"}:
        return "正式论文 / 学术资料"
    if normalized in {"github"}:
        return "代码工具 / 开源项目"
    if normalized in {"stackexchange", "hacker news"}:
        return "社区经验 / 工程讨论"
    if normalized in {"tavily", "firecrawl search", "exa", "brave search", "serpapi", "searxng", "bing html", "duckduckgo html", "jina bing reader", "jina search reader", "wikipedia", "anysearch"}:
        return "公开网页 / 通用搜索"
    return "其他来源"


def _query_variants(query: str) -> list[str]:
    base = str(query or "").strip()
    variants = [base] if base else []
    english_parts: list[str] = []
    mapping = [
        ("制氢", "hydrogen production"),
        ("加氢", "hydrogenation"),
        ("转化炉管", "reformer tube"),
        ("转化管", "reformer tube"),
        ("炉管", "furnace tube"),
        ("缺陷", "defects"),
        ("失效", "failure analysis"),
        ("裂纹", "crack"),
        ("蠕变", "creep"),
        ("腐蚀", "corrosion"),
        ("泄漏", "leakage"),
        ("损伤", "damage"),
        ("分析", "analysis"),
    ]
    for zh, en in mapping:
        if zh in base and en not in english_parts:
            english_parts.append(en)
    if any(term in base for term in ("异构体", "异构金属", "异质结构", "异质金属")):
        variants.extend([
            "异构金属 金属加工",
            "异质结构金属材料 加工 制备",
            "异构金属材料 设计 制造",
            "异构金属材料 强韧化 组织 性能",
            "梯度结构金属材料 制备 加工",
            "非均质金属材料 加工 制备",
            "heterostructured metals processing manufacturing",
            "heterostructured metallic materials",
            "heterostructured metals review",
            "heterostructured metals mechanical behavior",
            "heterostructured metals interfaces properties",
            "heterostructured metals additive manufacturing",
            "nanostructured heterostructured metals",
            "heterostructured metallic materials design manufacture",
            "gradient structured metals processing",
            "gradient structured metals mechanical properties",
            "nanostructured metals plastic deformation",
            "bulk nanostructured metals alloys severe plastic deformation",
            "ultrafine grained metals severe plastic deformation",
            "lamellar heterostructured metals",
            "bimodal grain structured metals",
            "harmonic structured metals processing",
            "heterogeneous metal materials processing",
        ])
    if english_parts:
        variants.append(" ".join(english_parts))
        if "reformer tube" in english_parts and "hydrogen production" in english_parts:
            variants.append("hydrogen reformer tube defects failure analysis")
            variants.append("reformer furnace tube hydrogen production damage analysis")
    spaced_cjk = " ".join(re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z0-9]+", base))
    if spaced_cjk and spaced_cjk != base:
        variants.append(spaced_cjk)
    seen: set[str] = set()
    output: list[str] = []
    for variant in variants:
        normalized = re.sub(r"\s+", " ", variant).strip()
        if not normalized or normalized.lower() in seen:
            continue
        seen.add(normalized.lower())
        output.append(normalized)
    return output[:20]


def _ppt_query_variants(query: str) -> list[str]:
    base = re.sub(r"\s+", " ", str(query or "")).strip()
    topic = re.sub(r"\bfiletype:(?:pptx?|pdf|docx?)\b", " ", base, flags=re.I)
    topic = re.sub(r"\b(?:OR|AND)\b", " ", topic, flags=re.I)
    topic = re.sub(r"\b(?:PPTX?|slides?|powerpoint)\b|课件|幻灯片|演示文稿", " ", topic, flags=re.I)
    topic = re.sub(r"\s+", " ", topic).strip() or base
    english_alias_query = _ppt_english_alias_query(topic)
    candidates = [
        f"{topic} filetype:pptx OR filetype:ppt",
        f"{topic} PPT 课件 幻灯片",
    ]
    if english_alias_query:
        candidates.extend([
            f"{english_alias_query} filetype:pptx OR filetype:ppt",
            f"{english_alias_query} powerpoint slides presentation",
        ])
    candidates.extend([
        f"{topic} powerpoint slides",
        f"{topic} presentation slideshare",
    ])
    seen: set[str] = set()
    output: list[str] = []
    for candidate in candidates:
        normalized = re.sub(r"\s+", " ", candidate).strip()
        key = normalized.lower()
        if normalized and key not in seen:
            seen.add(key)
            output.append(normalized)
    return output


def _ppt_english_alias_query(topic: str) -> str:
    value = str(topic or "").lower()
    groups = [
        ("制氢" in value or "氢" in value, "hydrogen"),
        ("转化管" in value or "转化炉管" in value or "炉管" in value, "reformer tube"),
        ("缺陷" in value or "失效" in value or "损伤" in value or "裂纹" in value, "defects failure analysis"),
        ("腐蚀" in value, "corrosion"),
        ("蠕变" in value, "creep"),
    ]
    terms = [term for enabled, term in groups if enabled]
    return " ".join(terms)


def _is_ppt_like_result(item: dict[str, str]) -> bool:
    value = " ".join(
        str(item.get(key, "") or "")
        for key in ("title", "url", "snippet")
    ).lower()
    return bool(re.search(r"(pptx?|powerpoint|slides?)|课件|幻灯片|演示文稿", value, flags=re.I))


def _filter_ppt_fallback_pool(query: str, results: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        item for item in results
        if not (_is_ppt_like_result(item) and not _is_ppt_topic_relevant(query, item))
    ]


def _is_ppt_topic_relevant(query: str, item: dict[str, str]) -> bool:
    value = " ".join(
        str(item.get(key, "") or "")
        for key in ("title", "url", "snippet")
    ).lower()
    topic = str(query or "").lower()
    generic_terms = {
        "ppt", "pptx", "powerpoint", "slides", "slide", "filetype", "课件", "幻灯片", "演示文稿",
        "总结", "资料", "相关", "方面", "分析", "报告", "汇报",
    }
    terms = [
        term for term in _query_relevance_terms(topic)
        if term not in generic_terms and not term.startswith("ppt")
    ]
    english_aliases = {
        "制氢": ["hydrogen", "hydrogen production"],
        "转化管": ["reformer tube", "reformer tubes", "reformer", "furnace tube"],
        "转化炉管": ["reformer tube", "reformer tubes", "furnace tube"],
        "炉管": ["furnace tube", "tube"],
        "缺陷": ["defect", "defects", "failure", "damage", "crack", "cracking"],
        "失效": ["failure", "failure analysis"],
        "损伤": ["damage"],
        "裂纹": ["crack", "cracking"],
        "蠕变": ["creep"],
        "腐蚀": ["corrosion"],
    }
    required_groups: list[list[str]] = []
    for zh, aliases in english_aliases.items():
        if zh in topic:
            required_groups.append([zh, *aliases])
    matched_groups = sum(1 for group in required_groups if any(term.lower() in value for term in group))
    if required_groups:
        required = min(len(required_groups), 2 if len(required_groups) <= 2 else 3)
        return matched_groups >= required
    matched_terms = sum(1 for term in terms if term in value)
    if len(terms) >= 3:
        return matched_terms >= 2
    if terms:
        return matched_terms >= 1
    return True


def _prefers_software_sources(query: str) -> bool:
    return bool(re.search(r"\b(api|sdk|mcp|github|gitlab|repository|repo|package|library|client|server)\b", query.lower()))


def _rank_search_results(query: str, results: list[dict[str, str]]) -> list[dict[str, str]]:
    def score(item: dict[str, str]) -> int:
        title = str(item.get("title", "")).lower()
        snippet = str(item.get("snippet", "")).lower()
        url = str(item.get("url", "")).lower()
        item_query = str(item.get("_query") or "")
        term_text = f"{query} {item_query}"
        terms = [term.lower() for term in re.findall(r"[\w\u4e00-\u9fff]+", term_text) if len(term) > 1]
        value = 0
        for term in terms:
            if term in title:
                value += 5
            if term in snippet:
                value += 2
            if term in url:
                value += 1
        if url.startswith("https://"):
            value += 1
        value += _source_quality_score(query, url, title)
        if item.get("_source") == "SearXNG":
            value += 2
        return value

    return sorted(results, key=score, reverse=True)


def _select_diverse_search_results(query: str, results: list[dict[str, str]], max_results: int) -> list[dict[str, str]]:
    ranked = _rank_search_results(query, results)
    selected: list[dict[str, str]] = []
    seen_fingerprints: set[str] = set()
    seen_sources: set[str] = set()
    for item in ranked:
        source = str(item.get("_source") or "")
        if not source or source in seen_sources:
            continue
        fingerprint = _result_fingerprint(item)
        if fingerprint in seen_fingerprints:
            continue
        selected.append(item)
        seen_sources.add(source)
        seen_fingerprints.add(fingerprint)
        if len(selected) >= max_results:
            return selected
    for item in ranked:
        fingerprint = _result_fingerprint(item)
        if fingerprint in seen_fingerprints:
            continue
        selected.append(item)
        seen_fingerprints.add(fingerprint)
        if len(selected) >= max_results:
            break
    return selected


def _filter_relevant_search_results(query: str, results: list[dict[str, str]]) -> list[dict[str, str]]:
    strict = [
        item for item in results
        if _search_result_relevance_score(
            str(item.get("_query") or query),
            _query_relevance_terms(str(item.get("_query") or query)),
            item,
        ) > 0
        and (
            not _is_heterostructured_metal_query(f"{query} {item.get('_query') or ''}")
            or _matches_heterostructured_metal_topic(item)
        )
    ]
    if not _is_heterostructured_metal_query(query):
        return strict

    seen = {_result_fingerprint(item) for item in strict}
    relaxed: list[dict[str, str]] = []
    for item in results:
        fingerprint = _result_fingerprint(item)
        if fingerprint in seen:
            continue
        if _matches_heterostructured_metal_topic_relaxed(item):
            relaxed.append(item)
            seen.add(fingerprint)
    return strict + relaxed


def _is_heterostructured_metal_query(query: str) -> bool:
    value = str(query or "").lower()
    return bool(
        any(term in value for term in ("异构体", "异构金属", "异质结构", "异质金属", "非均质"))
        or (
            any(term in value for term in ("heterostructured", "heterogeneous", "heterostructure"))
            and any(term in value for term in ("metal", "metals", "alloy", "alloys"))
        )
    )


def _matches_heterostructured_metal_topic(item: dict[str, str]) -> bool:
    value = " ".join(
        str(item.get(key, "") or "")
        for key in ("title", "url", "snippet")
    ).lower()
    hetero_terms = (
        "异构", "异质", "非均质", "梯度结构", "多尺度结构",
        "heterostructured", "heterostructure", "heterogeneous", "gradient structure",
        "lamellar", "bimodal", "nanostructured",
    )
    metal_terms = ("金属", "合金", "metal", "metals", "alloy", "alloys")
    process_terms = (
        "加工", "制备", "制造", "设计", "成形", "成型", "增材", "强韧", "性能", "机理", "组织", "变形",
        "processing", "manufacturing", "manufacture", "preparation", "fabrication", "design",
        "deformation", "mechanism", "mechanisms", "properties", "strength", "toughness",
    )
    blocked_terms = (
        "游戏", "图鉴", "角色", "武器突破", "鸣潮", "game", "wiki.kurobbs",
        "wastewater", "photocatal", "catalyst", "battery", "batteries", "energy storage",
        "oxide", "nanocomposite", "nanocomposites", "semiconductor", "mxene", "co2 reduction",
        "coating", "self-cleaning", "metallic artifacts", "tio2", "sio2",
    )
    return (
        any(term in value for term in hetero_terms)
        and any(term in value for term in metal_terms)
        and any(term in value for term in process_terms)
        and not any(term in value for term in blocked_terms)
    )


def _matches_heterostructured_metal_topic_relaxed(item: dict[str, str]) -> bool:
    value = " ".join(
        str(item.get(key, "") or "")
        for key in ("title", "url", "snippet")
    ).lower()
    hetero_terms = (
        "异构", "异质", "非均质", "梯度结构", "多尺度结构",
        "heterostructured", "heterostructure", "heterogeneous", "gradient structure",
    )
    metal_terms = ("金属", "合金", "metal", "metals", "metallic", "alloy", "alloys")
    useful_terms = (
        "材料", "组织", "性能", "强韧", "塑性", "制造", "制备", "加工", "设计", "增材", "成形", "成型",
        "materials", "properties", "strength", "ductility", "manufacturing", "processing",
        "fabrication", "design", "deformation", "interface", "interfaces", "defect", "defects",
        "mechanical", "behavior", "behaviour", "tribology", "review", "characterization",
    )
    blocked_terms = (
        "游戏", "图鉴", "角色", "武器突破", "鸣潮", "game", "wiki.kurobbs",
        "wastewater", "photocatal", "catalyst", "battery", "batteries", "energy storage",
        "oxide", "nanocomposite", "nanocomposites", "semiconductor", "mxene", "co2 reduction",
        "coating", "self-cleaning", "metallic artifacts", "tio2", "sio2",
    )
    source = str(item.get("_source") or "").lower()
    has_hetero = any(term in value for term in hetero_terms)
    has_metal = any(term in value for term in metal_terms)
    has_useful = any(term in value for term in useful_terms)
    is_scholarly = source in {"crossref", "openalex", "arxiv"}
    has_generic_scholarly_topic = "heterostructured materials" in value and is_scholarly
    return (
        has_hetero
        and ((has_metal and (has_useful or is_scholarly)) or (has_generic_scholarly_topic and has_useful))
        and not any(term in value for term in blocked_terms)
    )


def _query_relevance_terms(query: str) -> list[str]:
    cleaned = re.sub(r"site:[^\s)]+", " ", str(query or ""), flags=re.I)
    tokens = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", cleaned.lower())
    terms: list[str] = []
    for token in tokens:
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            if len(token) >= 2:
                terms.append(token)
            if len(token) >= 4:
                terms.extend(token[i : i + 2] for i in range(0, len(token) - 1))
        elif len(token) > 2:
            terms.append(token)
    seen: set[str] = set()
    deduped: list[str] = []
    for term in terms:
        if term in seen:
            continue
        seen.add(term)
        deduped.append(term)
    return deduped


def _search_result_relevance_score(query: str, terms: list[str], item: dict[str, str]) -> int:
    title = str(item.get("title", "")).lower()
    snippet = str(item.get("snippet", "")).lower()
    url = str(item.get("url", "")).lower()
    haystack = f"{title} {snippet} {url}"
    compact_query = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", query.lower())
    compact_haystack = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", haystack)
    if compact_query and len(compact_query) >= 4 and compact_query in compact_haystack:
        return 10

    score = 0
    matched_cjk = 0
    for term in terms:
        matched = term in haystack
        if re.fullmatch(r"[\u4e00-\u9fff]{2,}", term) and matched:
            matched_cjk += 1
        if term in title:
            score += 3
        elif term in snippet:
            score += 2
        elif term in url:
            score += 1

    has_cjk_query = any(re.fullmatch(r"[\u4e00-\u9fff]{2,}", term) for term in terms)
    if has_cjk_query and matched_cjk < 2:
        return 0
    alpha_terms = [term for term in terms if re.fullmatch(r"[a-z0-9]{3,}", term)]
    if alpha_terms:
        matched_alpha = sum(1 for term in alpha_terms if term in haystack)
        required = 1 if len(alpha_terms) == 1 else 2
        if matched_alpha < required:
            return 0
    return score


def _source_quality_score(query: str, url: str, title: str) -> int:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    compact_query = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", query.lower())
    host_compact = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", host)
    value = 0
    if compact_query and compact_query[: min(8, len(compact_query))] in host_compact:
        value += 8
    alpha_terms = [term for term in re.findall(r"[a-z0-9]+", query.lower()) if len(term) > 2]
    if alpha_terms and all(term in host_compact or term in path for term in alpha_terms[:3]):
        value += 8
    if any(part in path for part in ("/docs", "/documentation", "/developer", "/api", "/reference")):
        value += 5
    if host.endswith((".gov", ".edu", ".org")):
        value += 3
    if "github.com" in host or "gitlab.com" in host:
        value += 3
    if any(low in host for low in ("blog.csdn.net", "zhihu.com", "jianshu.com", "medium.com")):
        value -= 4
    if any(low in path for low in ("/login", "/signup", "/tag/", "/search")):
        value -= 3
    if len(title) > 120:
        value -= 1
    return value


def _is_low_quality_research_page(url: str) -> bool:
    host = urllib.parse.urlparse(url).netloc.lower()
    return any(low in host for low in ("blog.csdn.net", "zhihu.com", "jianshu.com", "medium.com"))


def _is_metadata_only_page(url: str) -> bool:
    host = urllib.parse.urlparse(url).netloc.lower()
    return host in {"doi.org", "dx.doi.org"} or host.endswith(".doi.org")


def _result_fingerprint(item: dict[str, str]) -> str:
    url = str(item.get("url") or "").strip().lower()
    if url:
        parsed = urllib.parse.urlparse(url)
        path = parsed.path.rstrip("/") or "/"
        return f"{parsed.scheme}://{parsed.netloc}{path}"
    title = re.sub(r"\s+", "", str(item.get("title") or "").lower())
    snippet = re.sub(r"\s+", "", str(item.get("snippet") or "").lower())[:120]
    return f"{title}:{snippet}" if title or snippet else ""


def _search_searxng(query: str, max_results: int, *, freshness: str = "") -> list[dict[str, str]]:
    if not _tcp_available(SEARXNG_URL):
        return []
    params = {"q": query, "format": "json", "language": "zh-CN"}
    if freshness:
        params["time_range"] = freshness
    try:
        data = json.loads(_fetch_text(f"{SEARXNG_URL}/search?{urllib.parse.urlencode(params)}"))
        items = []
        for row in data.get("results", [])[:max_results]:
            items.append({"title": row.get("title", ""), "url": row.get("url", ""), "snippet": row.get("content", "")})
        return items
    except Exception:
        return []


def _search_duckduckgo_instant(query: str, max_results: int) -> list[dict[str, str]]:
    try:
        url = "https://api.duckduckgo.com/?" + urllib.parse.urlencode({"q": query, "format": "json", "no_html": "1"})
        data = json.loads(_fetch_text(url))
    except Exception:
        return []
    rows: list[dict[str, str]] = []
    if data.get("AbstractText"):
        rows.append({"title": data.get("Heading", query), "url": data.get("AbstractURL", ""), "snippet": data.get("AbstractText", "")})
    for item in _flatten_duck_topics(data.get("RelatedTopics", [])):
        if len(rows) >= max_results:
            break
        rows.append({"title": item.get("Text", "")[:80], "url": item.get("FirstURL", ""), "snippet": item.get("Text", "")})
    return rows


def _search_crossref(query: str, max_results: int) -> list[dict[str, str]]:
    try:
        url = "https://api.crossref.org/works?" + urllib.parse.urlencode({"query": query, "rows": max_results})
        data = json.loads(_fetch_text_with_headers(url, {"User-Agent": DEFAULT_USER_AGENT}))
    except Exception:
        return []
    rows: list[dict[str, str]] = []
    for item in data.get("message", {}).get("items", [])[:max_results]:
        title = " ".join(item.get("title") or []).strip()
        if not title:
            continue
        url_value = item.get("URL") or item.get("DOI") or ""
        if url_value and not url_value.startswith(("http://", "https://")):
            url_value = "https://doi.org/" + url_value
        year = ""
        try:
            year = str(item.get("published-print", item.get("published-online", {})).get("date-parts", [[None]])[0][0] or "")
        except Exception:
            year = ""
        rows.append({"title": title, "url": url_value, "snippet": f"Crossref scholarly record {year}".strip()})
    return rows


def _search_openalex(query: str, max_results: int) -> list[dict[str, str]]:
    try:
        url = "https://api.openalex.org/works?" + urllib.parse.urlencode({"search": query, "per-page": max_results})
        data = json.loads(_fetch_text_with_headers(url, {"User-Agent": DEFAULT_USER_AGENT}))
    except Exception:
        return []
    rows: list[dict[str, str]] = []
    for item in data.get("results", [])[:max_results]:
        title = str(item.get("display_name") or "").strip()
        if not title:
            continue
        url_value = item.get("doi") or item.get("id") or ""
        abstract = item.get("abstract_inverted_index") or {}
        snippet = ""
        if isinstance(abstract, dict):
            words = sorted(((pos[0], word) for word, pos in abstract.items() if pos), key=lambda pair: pair[0])
            snippet = " ".join(word for _, word in words[:60])
        if not snippet:
            year = item.get("publication_year") or ""
            snippet = f"OpenAlex scholarly record {year}".strip()
        rows.append({"title": title, "url": url_value, "snippet": snippet})
    return rows


def _search_arxiv(query: str, max_results: int) -> list[dict[str, str]]:
    try:
        url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode({"search_query": f"all:{query}", "start": 0, "max_results": max_results})
        raw = _fetch_text_with_headers(url, {"User-Agent": DEFAULT_USER_AGENT})
        root = ET.fromstring(raw)
    except Exception:
        return []
    ns = {"a": "http://www.w3.org/2005/Atom"}
    rows: list[dict[str, str]] = []
    for entry in root.findall("a:entry", ns)[:max_results]:
        title = (entry.findtext("a:title", default="", namespaces=ns) or "").strip()
        url_value = (entry.findtext("a:id", default="", namespaces=ns) or "").strip()
        snippet = (entry.findtext("a:summary", default="", namespaces=ns) or "").strip()
        if title:
            rows.append({"title": re.sub(r"\s+", " ", title), "url": url_value, "snippet": re.sub(r"\s+", " ", snippet)[:500]})
    return rows


def _search_github(query: str, max_results: int) -> list[dict[str, str]]:
    try:
        url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode({"q": query, "per_page": min(max_results, 10)})
        data = json.loads(_fetch_text_with_headers(url, {"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/vnd.github+json"}))
    except Exception:
        return []
    rows: list[dict[str, str]] = []
    for item in data.get("items", [])[:max_results]:
        title = item.get("full_name") or item.get("name") or ""
        url_value = item.get("html_url") or ""
        snippet = item.get("description") or ""
        if title and url_value:
            rows.append({"title": title, "url": url_value, "snippet": snippet})
    return rows


def _search_brave_api(query: str, max_results: int) -> list[dict[str, str]]:
    if not BRAVE_SEARCH_API_KEY:
        return []
    try:
        url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode({
            "q": query,
            "count": min(max_results, 10),
        })
        data = json.loads(_fetch_text_with_headers(
            url,
            {
                "Accept": "application/json",
                "X-Subscription-Token": BRAVE_SEARCH_API_KEY,
                "User-Agent": DEFAULT_USER_AGENT,
            },
        ))
    except Exception:
        return []
    rows: list[dict[str, str]] = []
    for item in data.get("web", {}).get("results", [])[:max_results]:
        title = html.unescape(str(item.get("title") or "")).strip()
        url_value = str(item.get("url") or "").strip()
        snippet = _strip_tags(str(item.get("description") or ""))
        if title and url_value:
            rows.append({"title": title, "url": url_value, "snippet": snippet})
    return rows


def _search_tavily_api(query: str, max_results: int) -> list[dict[str, str]]:
    if not TAVILY_API_KEY:
        return []
    payload = {
        "query": query,
        "max_results": min(max_results, 10),
        "search_depth": "basic",
        "include_answer": False,
        "include_raw_content": False,
    }
    try:
        req = urllib.request.Request(
            "https://api.tavily.com/search",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {TAVILY_API_KEY}",
                "Content-Type": "application/json",
                "User-Agent": DEFAULT_USER_AGENT,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:
        return []
    rows: list[dict[str, str]] = []
    for item in data.get("results", [])[:max_results]:
        title = html.unescape(str(item.get("title") or "")).strip()
        url_value = str(item.get("url") or "").strip()
        snippet = _strip_tags(str(item.get("content") or ""))
        if title and url_value:
            rows.append({"title": title, "url": url_value, "snippet": snippet})
    return rows


def _search_firecrawl_api(query: str, max_results: int) -> list[dict[str, str]]:
    if not FIRECRAWL_API_KEY:
        return []
    payload = {
        "query": query,
        "limit": min(max_results, 10),
    }
    try:
        req = urllib.request.Request(
            f"{FIRECRAWL_API_URL}/search",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": DEFAULT_USER_AGENT,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=max(FETCH_TIMEOUT_SECONDS, 15)) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"Firecrawl Search API HTTP {exc.code}: {body}") from exc
    except Exception as exc:
        raise RuntimeError(f"Firecrawl Search API request failed: {exc}") from exc
    web_items = data.get("data", {}).get("web", [])
    if isinstance(data.get("data"), list):
        web_items = data.get("data", [])
    rows: list[dict[str, str]] = []
    for item in web_items[:max_results]:
        title = html.unescape(str(item.get("title") or item.get("url") or "")).strip()
        url_value = str(item.get("url") or "").strip()
        snippet = _strip_tags(str(item.get("description") or item.get("markdown") or ""))
        if title and url_value:
            rows.append({"title": title, "url": url_value, "snippet": snippet[:600]})
    return rows


def _search_exa_api(query: str, max_results: int) -> list[dict[str, str]]:
    if not EXA_API_KEY:
        return []
    payload = {
        "query": query,
        "numResults": min(max_results, 10),
        "type": "auto",
        "contents": {"highlights": True},
    }
    try:
        req = urllib.request.Request(
            "https://api.exa.ai/search",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "x-api-key": EXA_API_KEY,
                "Content-Type": "application/json",
                "User-Agent": DEFAULT_USER_AGENT,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:
        return []
    rows: list[dict[str, str]] = []
    for item in data.get("results", [])[:max_results]:
        title = html.unescape(str(item.get("title") or item.get("url") or "")).strip()
        url_value = str(item.get("url") or "").strip()
        highlights = item.get("highlights") or []
        snippet = " ".join(str(part) for part in highlights[:2]) or str(item.get("text") or "")
        if title and url_value:
            rows.append({"title": title, "url": url_value, "snippet": _strip_tags(snippet)[:500]})
    return rows


def _search_serpapi(query: str, max_results: int) -> list[dict[str, str]]:
    if not SERPAPI_API_KEY:
        return []
    try:
        url = "https://serpapi.com/search.json?" + urllib.parse.urlencode({
            "engine": "google",
            "q": query,
            "api_key": SERPAPI_API_KEY,
            "num": min(max_results, 10),
            "hl": "zh-cn",
        })
        data = json.loads(_fetch_text_with_headers(url, {"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"}))
    except Exception:
        return []
    rows: list[dict[str, str]] = []
    for item in data.get("organic_results", [])[:max_results]:
        title = html.unescape(str(item.get("title") or "")).strip()
        url_value = str(item.get("link") or "").strip()
        snippet = _strip_tags(str(item.get("snippet") or ""))
        if title and url_value:
            rows.append({"title": title, "url": url_value, "snippet": snippet})
    return rows


def _search_stackexchange(query: str, max_results: int) -> list[dict[str, str]]:
    try:
        url = "https://api.stackexchange.com/2.3/search/advanced?" + urllib.parse.urlencode({
            "order": "desc",
            "sort": "relevance",
            "q": query,
            "site": "stackoverflow",
            "pagesize": min(max_results, 10),
        })
        data = json.loads(_fetch_text_with_headers(url, {"User-Agent": DEFAULT_USER_AGENT}))
    except Exception:
        return []
    rows: list[dict[str, str]] = []
    for item in data.get("items", [])[:max_results]:
        title = html.unescape(item.get("title") or "")
        url_value = item.get("link") or ""
        tags = ", ".join(item.get("tags") or [])
        snippet = f"Stack Overflow question; tags: {tags}".strip()
        if title and url_value:
            rows.append({"title": title, "url": url_value, "snippet": snippet})
    return rows


def _search_hackernews(query: str, max_results: int) -> list[dict[str, str]]:
    try:
        url = "https://hn.algolia.com/api/v1/search?" + urllib.parse.urlencode({"query": query, "hitsPerPage": min(max_results, 10)})
        data = json.loads(_fetch_text_with_headers(url, {"User-Agent": DEFAULT_USER_AGENT}))
    except Exception:
        return []
    rows: list[dict[str, str]] = []
    for item in data.get("hits", [])[:max_results]:
        title = item.get("title") or item.get("story_title") or ""
        url_value = item.get("url") or (f"https://news.ycombinator.com/item?id={item.get('objectID')}" if item.get("objectID") else "")
        snippet = item.get("story_text") or item.get("comment_text") or f"Hacker News discussion by {item.get('author', '')}"
        if title and url_value:
            rows.append({"title": html.unescape(title), "url": url_value, "snippet": _strip_tags(snippet)[:400]})
    return rows


def _search_duckduckgo_html(query: str, max_results: int) -> list[dict[str, str]]:
    try:
        url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
        raw = _fetch_text(url)
    except Exception:
        return []
    rows: list[dict[str, str]] = []
    for block in re.findall(r'<div class="result(?: results_links_deep)?".*?</div>\s*</div>', raw, flags=re.I | re.S):
        title_match = re.search(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, flags=re.I | re.S)
        snippet_match = re.search(r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>|<div[^>]+class="result__snippet"[^>]*>(.*?)</div>', block, flags=re.I | re.S)
        if not title_match:
            continue
        url_value = _decode_bing_url(html.unescape(title_match.group(1)))
        parsed = urllib.parse.urlparse(url_value)
        if parsed.netloc.endswith("duckduckgo.com") and "uddg=" in parsed.query:
            url_value = urllib.parse.unquote(urllib.parse.parse_qs(parsed.query).get("uddg", [url_value])[0])
        title = _strip_tags(title_match.group(2))
        snippet = _strip_tags((snippet_match.group(1) or snippet_match.group(2)) if snippet_match else "")
        if title and url_value:
            rows.append({"title": title, "url": url_value, "snippet": snippet})
        if len(rows) >= max_results:
            break
    return rows


def _search_bing_html(query: str, max_results: int) -> list[dict[str, str]]:
    try:
        url = "https://www.bing.com/search?" + urllib.parse.urlencode({"q": query})
        raw = _fetch_text_with_headers(
            url,
            {
                "User-Agent": "Mozilla/5.0 " + DEFAULT_USER_AGENT,
                "Accept": "text/html,*/*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )
    except Exception:
        return []
    rows: list[dict[str, str]] = []
    for block in re.findall(r'<li class="b_algo".*?</li>', raw, flags=re.I | re.S):
        title_match = re.search(r'<h2.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.I | re.S)
        if not title_match:
            continue
        snippet_match = re.search(r'<p>(.*?)</p>', block, re.I | re.S)
        title = _strip_tags(title_match.group(2))
        url_value = _decode_bing_url(html.unescape(title_match.group(1)))
        snippet = _strip_tags(snippet_match.group(1) if snippet_match else "")
        if title and url_value.startswith(("http://", "https://")):
            rows.append({"title": title, "url": url_value, "snippet": snippet})
        if len(rows) >= max_results:
            break
    return rows


def _search_jina_bing(query: str, max_results: int) -> list[dict[str, str]]:
    try:
        bing_url = "http://www.bing.com/search?" + urllib.parse.urlencode({"q": query})
        url = "https://r.jina.ai/http://r.jina.ai/" + bing_url
        raw = _fetch_text_with_headers(url, _jina_headers())
    except Exception:
        return []
    rows: list[dict[str, str]] = []
    pattern = re.compile(r"^\s*\d+\.\s+##\s+\[(.*?)\]\((.*?)\)\s*$", re.M)
    matches = list(pattern.finditer(raw))
    for idx, match in enumerate(matches[:max_results]):
        title = _clean_markdown(match.group(1))
        url_value = _decode_bing_url(match.group(2))
        next_start = matches[idx + 1].start() if idx + 1 < len(matches) else len(raw)
        snippet = _clean_markdown(raw[match.end():next_start])[:300]
        if title and url_value.startswith(("http://", "https://")):
            rows.append({"title": title, "url": url_value, "snippet": snippet})
    return rows


def _search_jina(query: str, max_results: int) -> list[dict[str, str]]:
    try:
        url = "https://s.jina.ai/" + urllib.parse.quote(query)
        raw = _fetch_text_with_headers(url, _jina_headers())
    except Exception:
        return []
    if not raw.strip():
        return []
    rows = [{"title": f"Jina 综合搜索：{query}", "url": url, "snippet": raw[:1800]}]
    links = re.findall(r"https?://[^\s)>\]]+", raw)
    for link in links[: max(0, max_results - 1)]:
        rows.append({"title": link, "url": link, "snippet": ""})
    return rows[:max_results]


def _decode_bing_url(url_value: str) -> str:
    parsed = urllib.parse.urlparse(url_value)
    if not parsed.netloc.endswith("bing.com"):
        return url_value
    encoded = urllib.parse.parse_qs(parsed.query).get("u", [""])[0]
    if not encoded:
        match = re.search(r"[?&]u=([^&]+)", url_value)
        encoded = match.group(1) if match else ""
    if not encoded:
        return url_value
    # Bing commonly prefixes base64url target URLs with "a1".
    for candidate in (encoded, encoded[2:] if encoded.startswith("a1") else ""):
        if not candidate:
            continue
        try:
            padding = "=" * (-len(candidate) % 4)
            decoded = urllib.parse.unquote(__import__("base64").urlsafe_b64decode(candidate + padding).decode("utf-8", "replace"))
        except Exception:
            continue
        if decoded.startswith(("http://", "https://")):
            return decoded
    return url_value


def _search_wikipedia(query: str, max_results: int) -> list[dict[str, str]]:
    try:
        params = urllib.parse.urlencode({"search": query, "limit": max_results})
        data = json.loads(_fetch_text(f"https://zh.wikipedia.org/w/rest.php/v1/search/title?{params}"))
        return [
            {
                "title": row.get("title", ""),
                "url": "https://zh.wikipedia.org/wiki/" + urllib.parse.quote(row.get("key", row.get("title", ""))),
                "snippet": _strip_tags(row.get("excerpt", "")),
            }
            for row in data.get("pages", [])[:max_results]
        ]
    except Exception:
        return []


def _search_anysearch(query: str, max_results: int) -> list[dict[str, str]]:
    payload = {"method": "tools/call", "params": {"name": "search", "arguments": {"query": query, "max_results": max_results}}, "id": 1, "jsonrpc": "2.0"}
    try:
        req = urllib.request.Request(
            ANYSEARCH_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {ANYSEARCH_KEY}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = "\n".join(item.get("text", "") for item in data.get("result", {}).get("content", []))
        return [{"title": "AnySearch", "url": "", "snippet": text[:1500]}] if text else []
    except Exception:
        return []


def _flatten_duck_topics(items: list[Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if "Topics" in item:
            out.extend(_flatten_duck_topics(item.get("Topics", [])))
        elif item.get("Text"):
            out.append(item)
    return out


def _format_search_results(query: str, results: list[dict[str, str]], source: str) -> str:
    lines = [f"搜索 '{query}' 找到 {len(results)} 条结果（{source}）："]
    for idx, item in enumerate(results, start=1):
        title = item.get("title") or "无标题"
        url = item.get("url") or ""
        snippet = item.get("snippet") or ""
        lines.append(f"{idx}. {title}")
        if url:
            lines.append(f"   {url}")
        if snippet:
            lines.append(f"   {snippet[:260]}")
    return "\n".join(lines)


def _fetch_text(url: str) -> str:
    return _fetch_text_with_headers(url, {"User-Agent": DEFAULT_USER_AGENT, "Accept": "text/html,application/json,application/xml,text/xml,*/*"})


def _fetch_text_with_headers(url: str, headers: dict[str, str]) -> str:
    _throttle(url)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as resp:
        raw = resp.read()
        content_type = resp.headers.get("content-type", "")
    charset = "utf-8"
    match = re.search(r"charset=([\w-]+)", content_type, re.I)
    if match:
        charset = match.group(1)
    return raw.decode(charset, errors="replace")


def _jina_headers() -> dict[str, str]:
    headers = {"User-Agent": DEFAULT_USER_AGENT, "Accept": "text/plain, text/markdown, */*"}
    if JINA_API_KEY:
        headers["Authorization"] = f"Bearer {JINA_API_KEY}"
    return headers


def _select_read_backend(*, render: bool, backend: str) -> str:
    requested = str(backend or "auto").lower()
    if requested == "auto":
        requested = DEFAULT_READ_BACKEND
    if requested == "auto":
        if render:
            return "playwright"
        return "firecrawl" if ENABLE_FIRECRAWL and FIRECRAWL_API_KEY else "crawl4ai"
    if requested == "render":
        return "playwright"
    allowed = {"static", "playwright", "firecrawl", "crawl4ai", "jina_reader"}
    return requested if requested in allowed else "static"


def _fetch_by_backend(url: str, backend: str) -> str:
    if backend == "static":
        return _fetch_text(url)
    if backend == "playwright":
        if not ENABLE_PLAYWRIGHT:
            raise RuntimeError("Playwright 动态渲染已被 WEB_RESEARCH_ENABLE_PLAYWRIGHT 禁用")
        return _fetch_rendered(url)
    if backend == "crawl4ai":
        if not ENABLE_CRAWL4AI:
            raise RuntimeError("Crawl4AI 后端已被 WEB_RESEARCH_ENABLE_CRAWL4AI 禁用")
        return _fetch_crawl4ai(url)
    if backend == "firecrawl":
        if not ENABLE_FIRECRAWL:
            raise RuntimeError("Firecrawl 后端已被 WEB_RESEARCH_ENABLE_FIRECRAWL 禁用")
        if not FIRECRAWL_API_KEY:
            raise RuntimeError("Firecrawl 后端缺少 FIRECRAWL_API_KEY")
        return _fetch_firecrawl(url)
    if backend == "jina_reader":
        return _fetch_jina_reader(url)
    return _fetch_text(url)


def _fetch_rendered(url: str) -> str:
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"当前未安装 Playwright，无法渲染动态页面：{exc}") from exc
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=DEFAULT_USER_AGENT)
        page.goto(url, wait_until="networkidle", timeout=int(READ_TIMEOUT_SECONDS * 1000))
        content = page.content()
        browser.close()
        return content


def _fetch_crawl4ai(url: str) -> str:
    try:
        import asyncio
        from crawl4ai import AsyncWebCrawler  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"当前未安装 Crawl4AI，无法使用本地智能爬取后端：{exc}") from exc

    async def _crawl() -> str:
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=url)
            markdown = getattr(result, "markdown", None)
            if markdown:
                return str(markdown)
            cleaned_html = getattr(result, "cleaned_html", None)
            if cleaned_html:
                return str(cleaned_html)
            html_value = getattr(result, "html", None)
            if html_value:
                return str(html_value)
            return str(result)

    return _run_async(asyncio.wait_for(_crawl(), timeout=READ_TIMEOUT_SECONDS))


def _fetch_firecrawl(url: str) -> str:
    payload = {
        "url": url,
        "formats": ["markdown"],
        "onlyMainContent": True,
    }
    try:
        req = urllib.request.Request(
            f"{FIRECRAWL_API_URL}/scrape",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": DEFAULT_USER_AGENT,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=max(FETCH_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS)) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as exc:
        raise RuntimeError(f"Firecrawl 读取失败：{exc}") from exc
    if not data.get("success", True):
        raise RuntimeError(f"Firecrawl 读取失败：{data.get('error') or data}")
    body = data.get("data") if isinstance(data.get("data"), dict) else data
    markdown = str(body.get("markdown") or body.get("content") or body.get("html") or "").strip()
    if not markdown:
        raise RuntimeError("Firecrawl 未返回可用正文")
    return markdown


def _fetch_jina_reader(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise RuntimeError("Jina Reader 只支持 http/https URL")
    reader_url = "https://r.jina.ai/" + url
    return _fetch_text_with_headers(reader_url, _jina_headers())


def _run_async(coro: Any) -> Any:
    import asyncio
    import threading

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] = {}

    def _runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:  # pragma: no cover - defensive cross-thread propagation
            result["error"] = exc

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")


def _extract_readable_text(raw: str, url: str) -> str:
    try:
        import trafilatura  # type: ignore

        extracted = trafilatura.extract(raw, url=url, include_comments=False, include_tables=True)
        if extracted:
            return _clean_text(extracted)
    except Exception:
        pass
    parser = _TextExtractor()
    parser.feed(raw)
    return _clean_text(parser.text())


def _discover_from_site(url: str, *, max_items: int) -> list[dict[str, str]]:
    base = urllib.parse.urlparse(url)
    origin = f"{base.scheme}://{base.netloc}"
    candidates = [url, origin + "/robots.txt", origin + "/sitemap.xml", origin + "/feed", origin + "/rss"]
    found: list[dict[str, str]] = []
    for candidate in dict.fromkeys(candidates):
        try:
            raw = _fetch_text(candidate)
        except Exception:
            continue
        if candidate.endswith("robots.txt"):
            for line in raw.splitlines():
                if line.lower().startswith("sitemap:"):
                    found.append({"type": "sitemap", "url": line.split(":", 1)[1].strip()})
        found.extend(_extract_feed_links(raw, origin))
        if "urlset" in raw[:200] or "<sitemapindex" in raw[:500]:
            found.append({"type": "sitemap", "url": candidate})
        if len(found) >= max_items:
            break
    unique = []
    seen = set()
    for item in found:
        if item["url"] not in seen:
            seen.add(item["url"])
            unique.append(item)
    return unique[:max_items]


def _extract_feed_links(raw: str, origin: str) -> list[dict[str, str]]:
    links = []
    for match in re.finditer(r'<link[^>]+(?:type=["\']application/(?:rss|atom)\+xml["\'][^>]+href=["\']([^"\']+)["\']|href=["\']([^"\']+)["\'][^>]+type=["\']application/(?:rss|atom)\+xml["\'])', raw, re.I):
        href = match.group(1) or match.group(2)
        links.append({"type": "feed", "url": urllib.parse.urljoin(origin, html.unescape(href))})
    try:
        root = ET.fromstring(raw)
        if root.tag.lower().endswith(("rss", "feed")):
            links.append({"type": "feed", "url": origin})
    except Exception:
        pass
    return links


def _normalize_url(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    if not re.match(r"https?://", value, re.I):
        return ""
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return value


def _allowed_by_robots(url: str) -> bool:
    if not RESPECT_ROBOTS:
        return True
    parsed = urllib.parse.urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(robots_url)
        rp.read()
        return rp.can_fetch(DEFAULT_USER_AGENT, url)
    except Exception:
        return True


def _tcp_available(base_url: str) -> bool:
    parsed = urllib.parse.urlparse(base_url)
    if not parsed.hostname:
        return False
    import socket

    try:
        with socket.create_connection((parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)), timeout=1):
            return True
    except Exception:
        return False


def _throttle(url: str) -> None:
    host = urllib.parse.urlparse(url).netloc
    now = time.time()
    last = _LAST_HOST_ACCESS.get(host, 0)
    wait = MIN_HOST_INTERVAL - (now - last)
    if wait > 0:
        time.sleep(wait)
    _LAST_HOST_ACCESS[host] = time.time()


def _cache_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(CACHE_DB)), exist_ok=True)
    conn = sqlite3.connect(CACHE_DB)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS web_research_cache (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def _cache_key(kind: str, key: str) -> str:
    return hashlib.sha256(f"{kind}:{key}".encode("utf-8")).hexdigest()


def _cache_get(kind: str, key: str, *, max_age: int) -> str:
    try:
        conn = _cache_conn()
        row = conn.execute("SELECT value, updated_at FROM web_research_cache WHERE key = ?", (_cache_key(kind, key),)).fetchone()
        conn.close()
        if row and time.time() - float(row[1]) <= max_age:
            return str(row[0])
    except Exception:
        return ""
    return ""


def _cache_set(kind: str, key: str, value: str) -> None:
    try:
        conn = _cache_conn()
        conn.execute(
            "INSERT INTO web_research_cache (key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (_cache_key(kind, key), value, time.time()),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _cache_health() -> bool:
    try:
        conn = _cache_conn()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        return True
    except Exception:
        return False


def _module_available(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


def _strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", "", html.unescape(value or ""))


def _clean_text(value: str) -> str:
    lines = [re.sub(r"\s+", " ", html.unescape(line)).strip() for line in value.splitlines()]
    return "\n".join(line for line in lines if line)


def _clean_markdown(value: str) -> str:
    value = re.sub(r"[*_`#>]+", "", value or "")
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    return _clean_text(value)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip += 1
        if tag in {"p", "div", "section", "article", "h1", "h2", "h3", "li", "br"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip:
            self._skip -= 1
        if tag in {"p", "div", "section", "article", "li"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip and data.strip():
            self._parts.append(data.strip() + " ")

    def text(self) -> str:
        return "".join(self._parts)
