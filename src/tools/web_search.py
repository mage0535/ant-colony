"""Web search tool using Bing search."""
from __future__ import annotations

import logging
import re
import urllib.request

logger = logging.getLogger(__name__)


def web_search(query: str) -> str:
    if not query or len(query.strip()) < 2:
        return "请输入搜索关键词"

    q = urllib.request.quote(query.strip())

    try:
        url = f"https://www.bing.com/search?q={q}&count=5"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        resp = urllib.request.urlopen(req, timeout=15)
        html = resp.read().decode("utf-8", errors="replace")

        results = []
        
        # Extract search result items from Bing
        # Bing uses <li class="b_algo"> with <h2><a href="...">title</a></h2> and <p>abstract</p>
        items = re.findall(r'<li class="b_algo"[^>]*>(.*?)</li>', html, re.DOTALL)

        if items:
            results.append(f"Bing 搜索结果 ({query}):")
            for i, item in enumerate(items[:5]):
                # Extract title
                title_match = re.search(r'<h2[^>]*>.*?<a[^>]*>(.*?)</a>', item, re.DOTALL)
                title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip() if title_match else ""
                
                # Extract abstract/snippet
                abs_match = re.search(r'<p[^>]*>(.*?)</p>', item, re.DOTALL)
                abstract = re.sub(r'<[^>]+>', '', abs_match.group(1)).strip() if abs_match else ""
                abstract = abstract[:200]

                if title:
                    results.append(f"  {i+1}. {title}")
                    if abstract:
                        results.append(f"     {abstract}")
        else:
            # Fallback: try to find any meaningful text
            snippets = re.findall(r'<p class="b_lineclamp[^"]*"[^>]*>(.*?)</p>', html, re.DOTALL)
            if snippets:
                results.append(f"Bing 搜索结果 ({query}):")
                for i, s in enumerate(snippets[:5]):
                    text = re.sub(r'<[^>]+>', '', s).strip()[:200]
                    results.append(f"  {i+1}. {text}")

        if not results:
            return f'未找到"{query}"的相关信息'

        return "\n".join(results[:8])

    except Exception as e:
        logger.warning("Web search failed: %s", e)
        return f"搜索失败：{e}"
