"""Unified search — local SearXNG primary, AnySearch API fallback."""
from __future__ import annotations

import json
import logging
import ssl
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

SEARXNG_URL = "http://127.0.0.1:8899"
ANYSEARCH_URL = "https://api.anysearch.com/mcp"
ANYSEARCH_KEY = "as_sk_fbeb6d020cfad213dff6e3203923f49d"
SEARXNG_TIMEOUT = 10
ANYSEARCH_TIMEOUT = 20


def anysearch(query: str, max_results: int = 5) -> str:
    """Search: SearXNG → DuckDuckGo → AnySearch API (fallback chain)."""
    if not query:
        return "请输入搜索关键词"
    text = _searxng_search(query, max_results)
    if text:
        return text
    text = _duckduckgo_search(query, max_results)
    if text:
        return text
    logger.info("Local search backends unavailable; falling back to AnySearch API")
    return _anysearch_api(query, max_results)


def anysearch_domains(domain: str, query: str, sub_domain: str = "", max_results: int = 5) -> str:
    """Vertical domain search via AnySearch (SearXNG equivalent not available)."""
    return _anysearch_domains_api(domain, query, sub_domain, max_results)


# ---- DuckDuckGo (backend 2) ----

def _duckduckgo_search(query: str, max_results: int = 5) -> str:
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        if not results:
            return ""
        lines = [f"搜索 '{query}' 找到 {len(results)} 条结果 (DuckDuckGo):"]
        for r in results:
            title = r.get("title", "")
            snippet = r.get("body", "")[:150]
            url = r.get("href", "")
            lines.append(f"  [{title}]({url})")
            if snippet:
                lines.append(f"   {snippet}")
        return "\n".join(lines)
    except Exception as e:
        logger.debug("DuckDuckGo search failed: %s", e)
        return ""


# ---- SearXNG (backend 1) ----

def _searxng_search(query: str, max_results: int = 5) -> str:
    if not _searxng_available():
        return ""
    try:
        params = f"q={urllib.parse.quote(query)}&format=json&language=zh-CN"
        req = urllib.request.Request(f"{SEARXNG_URL}/search?{params}")
        with urllib.request.urlopen(req, timeout=SEARXNG_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
        results = data.get("results", [])
        if not results:
            return ""
        lines = [f"搜索 '{query}' 找到 {len(results)} 条结果:"]
        for r in results[:max_results]:
            title = r.get("title", "")
            snippet = r.get("content", "")[:150]
            url = r.get("url", "")
            lines.append(f"  [{title}]({url})")
            if snippet:
                lines.append(f"   {snippet}")
        return "\n".join(lines)
    except Exception as e:
        logger.debug("SearXNG search failed: %s", e)
        return ""


def _searxng_available() -> bool:
    import socket
    try:
        s = socket.create_connection(("127.0.0.1", 8899), timeout=1)
        s.close()
        return True
    except Exception:
        return False


# ---- AnySearch (fallback) ----

def _anysearch_api(query: str, max_results: int = 5) -> str:
    try:
        result = _anysearch_call("search", {"query": query, "max_results": max_results})
        content = result.get("result", {}).get("content", [])
        if content:
            return content[0].get("text", "")[:1500]
        return ""
    except Exception as e:
        logger.warning("AnySearch fallback also failed: %s", e)
        return f"搜索失败: {e}"


def _anysearch_domains_api(domain: str, query: str, sub_domain: str = "", max_results: int = 5) -> str:
    try:
        params = {"domain": domain, "query": query, "max_results": max_results}
        if sub_domain:
            params["sub_domain"] = sub_domain
        result = _anysearch_call("search", params)
        content = result.get("result", {}).get("content", [])
        if content:
            return content[0].get("text", "")[:1500]
        return "未找到结果"
    except Exception as e:
        return f"领域搜索失败: {e}"


def _anysearch_call(method: str, params: dict[str, Any]) -> dict[str, Any]:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    payload = {"method": "tools/call", "params": {"name": method, "arguments": params}, "id": 1, "jsonrpc": "2.0"}
    req = urllib.request.Request(ANYSEARCH_URL, data=json.dumps(payload).encode(),
                                 headers={"Authorization": f"Bearer {ANYSEARCH_KEY}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=ANYSEARCH_TIMEOUT, context=ctx) as resp:
        return json.loads(resp.read().decode())
