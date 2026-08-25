"""Unified compliant web search facade.

Search order:
1. Self-hosted SearXNG when SEARXNG_URL is reachable.
2. Public low-volume APIs such as DuckDuckGo Instant Answer and Wikipedia.
3. Optional AnySearch only when ANYSEARCH_KEY is provided by environment.

No API key is stored in source code.
"""
from __future__ import annotations

from src.tools.web_research_service import web_search


def anysearch(query: str, max_results: int = 5) -> str:
    return web_search(query, max_results=max_results)


def anysearch_domains(domain: str, query: str, sub_domain: str = "", max_results: int = 5) -> str:
    domains = [domain]
    if sub_domain:
        domains.insert(0, f"{sub_domain}.{domain}")
    return web_search(query, max_results=max_results, domains=domains)
