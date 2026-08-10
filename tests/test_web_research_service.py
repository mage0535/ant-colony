from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import patch


def _without_open_api_sources():
    from src.tools import web_research_service as svc

    stack = ExitStack()
    stack.enter_context(patch.object(svc, "_search_crossref", return_value=[]))
    stack.enter_context(patch.object(svc, "_search_openalex", return_value=[]))
    stack.enter_context(patch.object(svc, "_search_arxiv", return_value=[]))
    stack.enter_context(patch.object(svc, "_search_github", return_value=[]))
    stack.enter_context(patch.object(svc, "_search_stackexchange", return_value=[]))
    stack.enter_context(patch.object(svc, "_search_hackernews", return_value=[]))
    return stack


def test_anysearch_client_does_not_embed_api_key() -> None:
    from pathlib import Path

    text = Path("src/tools/anysearch_client.py").read_text(encoding="utf-8")

    assert "as_sk_" not in text
    assert "ANYSEARCH_KEY" in text or "web_search" in text


def test_web_search_uses_searxng_when_available() -> None:
    from src.tools import web_research_service as svc

    payload = {
        "results": [
            {"title": "Result A", "url": "https://example.com/a", "content": "Snippet A"},
            {"title": "Result B", "url": "https://example.com/b", "content": "Snippet B"},
        ]
    }

    with patch.object(svc, "_tcp_available", return_value=True), \
         patch.object(svc, "_fetch_text", return_value=__import__("json").dumps(payload)):
        result = svc.web_search("query", max_results=2)

    assert "SearXNG" in result
    assert "Result A" in result
    assert "https://example.com/a" in result


def test_web_search_falls_back_to_duckduckgo_html() -> None:
    from src.tools import web_research_service as svc

    html = """
    <div class="result">
      <h2><a class="result__a" href="https://example.com/a">Example A</a></h2>
      <a class="result__snippet">Snippet A</a>
    </div></div>
    """

    with patch.object(svc, "_tcp_available", return_value=False), \
         patch.object(svc, "_search_duckduckgo_instant", return_value=[]), \
         patch.object(svc, "_fetch_text", return_value=html):
        result = svc.web_search("query", max_results=2)

    assert "DuckDuckGo HTML" in result
    assert "Example A" in result
    assert "https://example.com/a" in result


def test_web_search_falls_back_to_jina_reader() -> None:
    from src.tools import web_research_service as svc

    raw = "Open-Meteo API\nhttps://open-meteo.com/\nFree weather forecast API"

    with patch.object(svc, "_tcp_available", return_value=False), \
         patch.object(svc, "_search_duckduckgo_instant", return_value=[]), \
         patch.object(svc, "_search_duckduckgo_html", return_value=[]), \
         patch.object(svc, "_fetch_text_with_headers", return_value=raw):
        result = svc.web_search("Open-Meteo API", max_results=2)

    assert "Jina Search Reader" in result
    assert "Open-Meteo API" in result
    assert "https://open-meteo.com/" in result


def test_web_search_uses_jina_bing_reader_before_bing_html() -> None:
    from src.tools import web_research_service as svc

    raw = """
    1.   ## [**Open-Meteo** Docs](https://www.bing.com/ck/a?u=a1aHR0cHM6Ly9vcGVuLW1ldGVvLmNvbS9lbi9kb2Nz)

    Weather API documentation.
    """

    with patch.object(svc, "_tcp_available", return_value=False), \
         patch.object(svc, "_search_duckduckgo_instant", return_value=[]), \
         patch.object(svc, "_search_duckduckgo_html", return_value=[]), \
         patch.object(svc, "_fetch_text_with_headers", return_value=raw), \
         patch.object(svc, "_search_bing_html", return_value=[]) as bing:
        result = svc.web_search("Open-Meteo API", max_results=2)

    assert "Jina Bing Reader" in result
    assert "Open-Meteo Docs" in result
    assert "https://open-meteo.com/en/docs" in result
    bing.assert_not_called()


def test_web_search_falls_back_to_bing_html_when_jina_is_disabled() -> None:
    from src.tools import web_research_service as svc

    rows = [{"title": "Bing Result", "url": "https://example.com/bing", "snippet": "Bing snippet"}]

    with patch.object(svc, "_tcp_available", return_value=False), \
         patch.object(svc, "_search_duckduckgo_instant", return_value=[]), \
         patch.object(svc, "_search_duckduckgo_html", return_value=[]), \
         patch.object(svc, "ENABLE_JINA", False), \
         patch.object(svc, "_search_bing_html", return_value=rows), \
         patch.object(svc, "_search_jina", return_value=[]) as jina:
        result = svc.web_search("query", max_results=2)

    assert "Bing HTML" in result
    assert "Bing Result" in result
    jina.assert_not_called()


def test_web_search_aggregate_dedupes_and_reports_sources() -> None:
    from src.tools import web_research_service as svc

    with _without_open_api_sources(), \
         patch.object(svc, "ENABLE_SEARXNG", True), \
         patch.object(svc, "ENABLE_SLOW_SEARCH_SOURCES", True), \
         patch.object(svc, "_search_searxng", return_value=[{"title": "Open-Meteo Docs", "url": "https://open-meteo.com/en/docs", "snippet": "Weather API"}]), \
         patch.object(svc, "_search_duckduckgo_instant", return_value=[]), \
         patch.object(svc, "_search_duckduckgo_html", return_value=[{"title": "Duplicate Docs", "url": "https://open-meteo.com/en/docs", "snippet": "Duplicate"}]), \
         patch.object(svc, "_search_jina_bing", return_value=[{"title": "Open-Meteo Home", "url": "https://open-meteo.com/", "snippet": "Forecast API"}]), \
         patch.object(svc, "_search_bing_html", return_value=[]), \
         patch.object(svc, "_search_jina", return_value=[]), \
         patch.object(svc, "_search_wikipedia", return_value=[]):
        result = svc.web_search_aggregate("Open-Meteo API", max_results=5)

    assert "多源搜索" in result
    assert "SearXNG" in result
    assert "Jina Bing Reader" in result
    assert result.count("https://open-meteo.com/en/docs") == 1
    assert "来源诊断" in result


def test_search_ranking_prefers_official_docs_over_blog_posts() -> None:
    from src.tools import web_research_service as svc

    rows = [
        {"title": "Open-Meteo完全免费的天气 API查询", "url": "https://blog.csdn.net/example/article/details/1", "snippet": "Open-Meteo API tutorial", "_source": "Bing HTML"},
        {"title": "Docs | Open-Meteo.com", "url": "https://open-meteo.com/en/docs", "snippet": "Weather API documentation", "_source": "Bing HTML"},
    ]

    ranked = svc._rank_search_results("Open-Meteo API", rows)

    assert ranked[0]["url"] == "https://open-meteo.com/en/docs"


def test_search_selection_keeps_representative_results_from_each_source() -> None:
    from src.tools import web_research_service as svc

    rows = [
        {"title": f"Open-Meteo API Crossref {idx}", "url": f"https://doi.org/10.{idx}", "snippet": "Open-Meteo API", "_source": "Crossref"}
        for idx in range(5)
    ] + [
        {"title": "Open-Meteo API Tavily", "url": "https://example.com/tavily", "snippet": "Open-Meteo API", "_source": "Tavily"},
        {"title": "Open-Meteo API Firecrawl", "url": "https://example.com/firecrawl", "snippet": "Open-Meteo API", "_source": "Firecrawl Search"},
    ]

    selected = svc._select_diverse_search_results("Open-Meteo API", rows, max_results=4)
    sources = {item["_source"] for item in selected}

    assert "Crossref" in sources
    assert "Tavily" in sources
    assert "Firecrawl Search" in sources


def test_web_search_aggregate_filters_unrelated_bing_noise() -> None:
    from src.tools import web_research_service as svc

    rows = [
        {"title": "Excel 如何制作组织架构图", "url": "https://jingyan.baidu.com/example", "snippet": "Excel 制作组织架构图", "_source": "Bing HTML"},
        {"title": "calibre 中如何使用词典？", "url": "https://www.zhihu.com/question/1", "snippet": "词典和电子书使用方法", "_source": "Bing HTML"},
        {"title": "制氢转化管缺陷与失效分析", "url": "https://example.com/hydrogen-reformer-tube", "snippet": "介绍制氢装置转化管常见缺陷、蠕变、裂纹和检验方法", "_source": "Bing HTML"},
    ]

    with _without_open_api_sources(), \
         patch.object(svc, "_search_searxng", return_value=[]), \
         patch.object(svc, "_search_duckduckgo_instant", return_value=[]), \
         patch.object(svc, "_search_duckduckgo_html", return_value=[]), \
         patch.object(svc, "_search_jina_bing", return_value=[]), \
         patch.object(svc, "_search_bing_html", return_value=rows), \
         patch.object(svc, "_search_jina", return_value=[]), \
         patch.object(svc, "_search_wikipedia", return_value=[]):
        result = svc.web_search_aggregate("制氢转化管缺陷", max_results=10)

    assert "制氢转化管缺陷与失效分析" in result
    assert "Excel 如何制作组织架构图" not in result
    assert "calibre 中如何使用词典" not in result
    assert "Relevance filter: kept 1/3" in result


def test_web_search_aggregate_reports_no_results_when_only_noise() -> None:
    from src.tools import web_research_service as svc

    rows = [
        {"title": "Excel 如何制作组织架构图", "url": "https://jingyan.baidu.com/example", "snippet": "Excel 制作组织架构图", "_source": "Bing HTML"},
        {"title": "英语词典 App 哪个比较好", "url": "https://www.zhihu.com/question/2", "snippet": "英语词典推荐", "_source": "Bing HTML"},
    ]

    with _without_open_api_sources(), \
         patch.object(svc, "_search_searxng", return_value=[]), \
         patch.object(svc, "_search_duckduckgo_instant", return_value=[]), \
         patch.object(svc, "_search_duckduckgo_html", return_value=[]), \
         patch.object(svc, "_search_jina_bing", return_value=[]), \
         patch.object(svc, "_search_bing_html", return_value=rows), \
         patch.object(svc, "_search_jina", return_value=[]), \
         patch.object(svc, "_search_wikipedia", return_value=[]):
        result = svc.web_search_aggregate("制氢转化管缺陷", max_results=10)

    assert "未找到" in result or "鏈壘鍒" in result
    assert "Excel 如何制作组织架构图" not in result
    assert "英语词典" not in result


def test_web_search_aggregate_uses_crossref_for_scholarly_results() -> None:
    from src.tools import web_research_service as svc

    rows = [
        {
            "title": "Metallurgical Investigation of Hydrogen Reformer Tube Rupture",
            "url": "https://doi.org/10.5006/c2023-18930",
            "snippet": "Crossref scholarly record 2023",
        }
    ]

    with patch.object(svc, "_search_searxng", return_value=[]), \
         patch.object(svc, "_search_crossref", return_value=rows), \
         patch.object(svc, "_search_openalex", return_value=[]), \
         patch.object(svc, "_search_arxiv", return_value=[]), \
         patch.object(svc, "_search_github", return_value=[]), \
         patch.object(svc, "_search_stackexchange", return_value=[]), \
         patch.object(svc, "_search_hackernews", return_value=[]), \
         patch.object(svc, "_search_duckduckgo_instant", return_value=[]), \
         patch.object(svc, "_search_duckduckgo_html", return_value=[]), \
         patch.object(svc, "_search_jina_bing", return_value=[]), \
         patch.object(svc, "_search_bing_html", return_value=[]), \
         patch.object(svc, "_search_jina", return_value=[]), \
         patch.object(svc, "_search_wikipedia", return_value=[]):
        result = svc.web_search_aggregate("hydrogen reformer tube defects", max_results=5)

    assert "Crossref" in result
    assert "Hydrogen Reformer Tube Rupture" in result
    assert "https://doi.org/10.5006/c2023-18930" in result
    assert "正式论文 / 学术资料" in result


def test_web_search_aggregate_uses_engineering_community_sources() -> None:
    from src.tools import web_research_service as svc

    stack_rows = [{"title": "Open-Meteo latitude and longitude auto fill in possible?", "url": "https://stackoverflow.com/questions/1", "snippet": "Stack Overflow question; tags: python"}]
    hn_rows = [{"title": "Show HN: Weather API tool", "url": "https://news.ycombinator.com/item?id=1", "snippet": "Hacker News discussion"}]

    with patch.object(svc, "_search_searxng", return_value=[]), \
         patch.object(svc, "_search_crossref", return_value=[]), \
         patch.object(svc, "_search_openalex", return_value=[]), \
         patch.object(svc, "_search_arxiv", return_value=[]), \
         patch.object(svc, "_search_github", return_value=[]), \
         patch.object(svc, "_search_stackexchange", return_value=stack_rows), \
         patch.object(svc, "_search_hackernews", return_value=hn_rows), \
         patch.object(svc, "_search_bing_html", return_value=[]):
        result = svc.web_search_aggregate("Open-Meteo API python", max_results=5)

    assert "社区经验 / 工程讨论" in result
    assert "StackExchange" in result
    assert "Hacker News" in result


def test_web_search_aggregate_uses_optional_search_api_sources() -> None:
    from src.tools import web_research_service as svc

    tavily_rows = [{"title": "Tavily result", "url": "https://example.com/tavily", "snippet": "Open-Meteo API result"}]
    firecrawl_rows = [{"title": "Firecrawl result", "url": "https://example.com/firecrawl", "snippet": "Open-Meteo API result"}]
    exa_rows = [{"title": "Exa result", "url": "https://example.com/exa", "snippet": "Open-Meteo API semantic result"}]
    brave_rows = [{"title": "Brave result", "url": "https://example.com/brave", "snippet": "Open-Meteo API result"}]
    serp_rows = [{"title": "SerpAPI result", "url": "https://example.com/serp", "snippet": "Open-Meteo API result"}]

    with patch.object(svc, "ENABLE_SEARXNG", False), \
         patch.object(svc, "_search_crossref", return_value=[]), \
         patch.object(svc, "_search_openalex", return_value=[]), \
         patch.object(svc, "_search_arxiv", return_value=[]), \
         patch.object(svc, "_search_tavily_api", return_value=tavily_rows), \
         patch.object(svc, "_search_firecrawl_api", return_value=firecrawl_rows), \
         patch.object(svc, "_search_exa_api", return_value=exa_rows), \
         patch.object(svc, "_search_brave_api", return_value=brave_rows), \
         patch.object(svc, "_search_serpapi", return_value=serp_rows), \
         patch.object(svc, "_search_github", return_value=[]), \
         patch.object(svc, "_search_stackexchange", return_value=[]), \
         patch.object(svc, "_search_hackernews", return_value=[]), \
         patch.object(svc, "_search_bing_html", return_value=[]):
        result = svc.web_search_aggregate("Open-Meteo API", max_results=8)

    assert "Tavily" in result
    assert "Firecrawl Search" in result
    assert "Exa" in result
    assert "Brave Search" in result
    assert "SerpAPI" in result


def test_web_search_aggregate_falls_back_when_requested_source_is_empty() -> None:
    from src.tools import web_research_service as svc

    bing_rows = [
        {
            "title": "异质结构金属材料加工与制备研究",
            "url": "https://example.com/heterostructured-metals",
            "snippet": "异构金属 金属加工 异质结构金属材料 制备 工艺",
        }
    ]

    with patch.object(svc, "ENABLE_SEARXNG", False), \
         patch.object(svc, "_search_crossref", return_value=[]), \
         patch.object(svc, "_search_openalex", return_value=[]), \
         patch.object(svc, "_search_arxiv", return_value=[]), \
         patch.object(svc, "_search_tavily_api", return_value=[]), \
         patch.object(svc, "_search_firecrawl_api", return_value=[]), \
         patch.object(svc, "_search_exa_api", return_value=[]), \
         patch.object(svc, "_search_brave_api", return_value=[]), \
         patch.object(svc, "_search_serpapi", return_value=[]), \
         patch.object(svc, "_search_github", return_value=[]), \
         patch.object(svc, "_search_stackexchange", return_value=[]), \
         patch.object(svc, "_search_hackernews", return_value=[]), \
         patch.object(svc, "_search_bing_html", return_value=bing_rows), \
         patch.object(svc, "_search_anysearch", return_value=[]):
        result = svc.web_search_aggregate(
            "异构体金属加工",
            max_results=5,
            include_sources=["AnySearch"],
        )

    assert "异质结构金属材料加工与制备研究" in result
    assert "Bing HTML" in result
    assert "Source fallback" in result
    assert "AnySearch: 0" in result


def test_web_search_aggregate_recommendation_order_can_show_twenty_items() -> None:
    from src.tools import web_research_service as svc

    rows = [
        {
            "title": f"异质结构金属材料加工资料 {idx}",
            "url": f"https://example.com/heterostructured-metal-{idx}",
            "snippet": "异构金属 异质结构金属材料 加工 制备",
        }
        for idx in range(1, 21)
    ]

    with patch.object(svc, "ENABLE_SEARXNG", False), \
         patch.object(svc, "_search_crossref", return_value=[]), \
         patch.object(svc, "_search_openalex", return_value=[]), \
         patch.object(svc, "_search_arxiv", return_value=[]), \
         patch.object(svc, "_search_tavily_api", return_value=rows), \
         patch.object(svc, "_search_firecrawl_api", return_value=[]), \
         patch.object(svc, "_search_exa_api", return_value=[]), \
         patch.object(svc, "_search_brave_api", return_value=[]), \
         patch.object(svc, "_search_serpapi", return_value=[]), \
         patch.object(svc, "_search_github", return_value=[]), \
         patch.object(svc, "_search_stackexchange", return_value=[]), \
         patch.object(svc, "_search_hackernews", return_value=[]), \
         patch.object(svc, "_search_bing_html", return_value=[]), \
         patch.object(svc, "_search_anysearch", return_value=[]):
        result = svc.web_search_aggregate("异构体金属加工", max_results=20)

    assert "命中 20 条高相关结果" in result
    assert "20. 异质结构金属材料加工资料" in result


def test_query_variants_expand_heterostructured_metal_terms() -> None:
    from src.tools import web_research_service as svc

    variants = svc._query_variants("异构体金属加工")

    assert "异构金属 金属加工" in variants
    assert "异质结构金属材料 加工 制备" in variants
    assert "异构金属材料 设计 制造" in variants
    assert any("heterostructured metals" in item for item in variants)


def test_query_variants_include_scholarly_english_heterostructured_terms() -> None:
    from src.tools import web_research_service as svc

    variants = svc._query_variants("异构体金属加工")

    assert len(variants) > 8
    assert "heterostructured metallic materials" in variants
    assert "heterostructured metals review" in variants
    assert "heterostructured metals mechanical behavior" in variants


def test_heterostructured_query_limits_expanded_variants_per_source() -> None:
    from src.tools import web_research_service as svc

    variants = svc._query_variants("异构体金属加工")

    crossref_variants = svc._variants_for_source("异构体金属加工", "Crossref", variants, "variants")
    assert len(crossref_variants) == 10
    assert "异构金属 金属加工" not in crossref_variants
    assert "bulk nanostructured metals alloys severe plastic deformation" in crossref_variants
    assert len(svc._variants_for_source("异构体金属加工", "arXiv", variants, "variants")) == 8
    assert len(svc._variants_for_source("异构体金属加工", "Bing HTML", variants, "variants")) == 8
    assert svc._per_source_call_limit("Crossref", 80, 16) == 30
    assert svc._per_source_call_limit("Bing HTML", 80, 6) == 12


def test_heterostructured_metal_query_filters_broad_metal_processing_noise() -> None:
    from src.tools import web_research_service as svc

    rows = [
        {
            "title": "金属材料加工工艺探讨",
            "url": "https://example.com/broad-metal-processing",
            "snippet": "金属材料 加工 工艺",
            "_source": "Crossref",
            "_query": "异构体金属加工",
        },
        {
            "title": "异构金属液滴- 鸣潮图鉴",
            "url": "https://wiki.kurobbs.com/mc/item/1",
            "snippet": "用于游戏角色的武器突破材料",
            "_source": "Tavily",
            "_query": "异构金属 金属加工",
        },
        {
            "title": "异质结构金属材料加工与制备研究",
            "url": "https://example.com/heterostructured-metal-processing",
            "snippet": "异构金属 异质结构金属材料 制备 加工 工艺",
            "_source": "Bing HTML",
            "_query": "异质结构金属材料 加工 制备",
        },
    ]

    filtered = svc._filter_relevant_search_results("异构体金属加工", rows)

    assert [item["title"] for item in filtered] == ["异质结构金属材料加工与制备研究"]


def test_heterostructured_metal_filter_relaxes_to_keep_scholarly_topic_results() -> None:
    from src.tools import web_research_service as svc

    rows = [
        {
            "title": "Generic metal processing handbook",
            "url": "https://example.com/generic-metal",
            "snippet": "metal processing",
            "_source": "Bing HTML",
            "_query": "heterostructured metals processing",
        },
        {
            "title": "Heterostructured metals: interfaces and mechanical properties",
            "url": "https://doi.org/10.1000/hetero",
            "snippet": "Crossref scholarly record",
            "_source": "Crossref",
            "_query": "heterostructured metals processing",
        },
        {
            "title": "Heterostructured metallic materials design and manufacture",
            "url": "https://example.com/heterostructured-metallic-materials",
            "snippet": "materials properties strength ductility interfaces",
            "_source": "Tavily",
            "_query": "heterostructured metallic materials design manufacture",
        },
    ]

    filtered = svc._filter_relevant_search_results("heterostructured metals processing", rows)
    titles = [item["title"] for item in filtered]

    assert "Heterostructured metals: interfaces and mechanical properties" in titles
    assert "Heterostructured metallic materials design and manufacture" in titles
    assert "Generic metal processing handbook" not in titles


def test_heterostructured_relaxed_filter_keeps_review_and_excludes_energy_noise() -> None:
    from src.tools import web_research_service as svc

    rows = [
        {
            "title": "Towards full-scaling tribology of heterostructured metals: A review",
            "url": "https://doi.org/10.1000/tribology-review",
            "snippet": "mechanical behavior and properties of heterostructured metals",
            "_source": "Crossref",
            "_query": "heterostructured metals review",
        },
        {
            "title": "Mechanical Behavior of Bulk Nanostructured and Heterostructured Metals",
            "url": "https://doi.org/10.1000/mechanical-behavior",
            "snippet": "bulk nanostructured and heterostructured metals",
            "_source": "Crossref",
            "_query": "heterostructured metals mechanical behavior",
        },
        {
            "title": "Metal Oxide Heterostructured Nanocomposites for Wastewater Treatment",
            "url": "https://doi.org/10.1000/wastewater",
            "snippet": "photocatalytic catalyst materials",
            "_source": "Crossref",
            "_query": "heterostructured metallic materials",
        },
        {
            "title": "Heterostructured Metallic 1T-VSe2/Ti3C2Tx MXene Nanosheets for Energy Storage",
            "url": "https://doi.org/10.1000/energy-storage",
            "snippet": "battery electrode and energy storage",
            "_source": "Crossref",
            "_query": "heterostructured metallic materials",
        },
        {
            "title": "Electron transport properties of heterogeneous interfaces in solid electrolyte interphase on lithium metal anodes",
            "url": "http://arxiv.org/abs/2501.12686v1",
            "snippet": "rechargeable batteries and electron transport properties",
            "_source": "arXiv",
            "_query": "heterostructured metals interfaces properties",
        },
        {
            "title": "Heterostructured TiO2/SiO2 Coating with Self-Cleaning Properties for Metallic Artifacts",
            "url": "https://doi.org/10.1000/self-cleaning",
            "snippet": "visible-light-induced self-cleaning coating",
            "_source": "Crossref",
            "_query": "heterostructured metallic materials",
        },
    ]

    filtered = svc._filter_relevant_search_results("heterostructured metals processing", rows)
    titles = [item["title"] for item in filtered]

    assert "Towards full-scaling tribology of heterostructured metals: A review" in titles
    assert "Mechanical Behavior of Bulk Nanostructured and Heterostructured Metals" in titles
    assert "Metal Oxide Heterostructured Nanocomposites for Wastewater Treatment" not in titles
    assert "Heterostructured Metallic 1T-VSe2/Ti3C2Tx MXene Nanosheets for Energy Storage" not in titles
    assert "Electron transport properties of heterogeneous interfaces in solid electrolyte interphase on lithium metal anodes" not in titles
    assert "Heterostructured TiO2/SiO2 Coating with Self-Cleaning Properties for Metallic Artifacts" not in titles


def test_dedupe_search_results_drops_relative_redirect_urls() -> None:
    from src.tools import web_research_service as svc

    rows = [
        {"title": "redirect", "url": "/goto?url=abc", "snippet": "异构金属"},
        {"title": "direct", "url": "https://example.com/direct", "snippet": "异构金属"},
        {"title": "summary only", "url": "", "snippet": "异构金属"},
    ]

    deduped = svc._dedupe_search_results(rows)

    assert [item["title"] for item in deduped] == ["direct", "summary only"]


def test_web_ppt_search_prefers_ppt_like_results_and_reports_sources() -> None:
    from src.tools import web_research_service as svc

    rows = [
        {"title": "制氢转化管缺陷总结 PPT", "url": "https://example.com/reformer-defects.pptx", "snippet": "制氢转化管 缺陷 课件"},
        {"title": "制氢转化管缺陷论文", "url": "https://example.com/paper", "snippet": "制氢转化管 缺陷 分析"},
    ]

    with patch.object(svc, "_search_tavily_api", return_value=[]), \
         patch.object(svc, "_search_firecrawl_api", return_value=[]), \
         patch.object(svc, "_search_exa_api", return_value=[]), \
         patch.object(svc, "_search_brave_api", return_value=[]), \
         patch.object(svc, "_search_serpapi", return_value=[]), \
         patch.object(svc, "_search_searxng", return_value=[]), \
         patch.object(svc, "_search_bing_html", return_value=rows), \
         patch.object(svc, "_search_anysearch", return_value=[]):
        result = svc.web_ppt_search("制氢转化管缺陷 PPT PPTX 课件", max_results=5)

    assert "专项 PPT 检索" in result
    assert "reformer-defects.pptx" in result
    assert "https://example.com/paper" not in result
    assert "Bing HTML" in result


def test_web_ppt_search_filters_generic_hydrogen_ppt_when_core_terms_missing() -> None:
    from src.tools import web_research_service as svc

    rows = [
        {
            "title": "氢的制储运加现状及趋势展望",
            "url": "https://example.com/hydrogen-general.pdf",
            "snippet": "PPT模板下载 氢能产业链 制氢 储运氢 加氢站",
        }
    ]

    with patch.object(svc, "_search_tavily_api", return_value=rows), \
         patch.object(svc, "_search_firecrawl_api", return_value=[]), \
         patch.object(svc, "_search_exa_api", return_value=[]), \
         patch.object(svc, "_search_brave_api", return_value=[]), \
         patch.object(svc, "_search_serpapi", return_value=[]), \
         patch.object(svc, "_search_searxng", return_value=[]), \
         patch.object(svc, "_search_bing_html", return_value=[]), \
         patch.object(svc, "_search_anysearch", return_value=[]):
        result = svc.web_ppt_search("制氢转化管缺陷 PPT PPTX 课件", max_results=5)

    assert "未找到明确高相关 PPT/PPTX/课件结果" in result
    assert "氢的制储运加现状及趋势展望" not in result
    assert "Relevance filter: kept 0/1" in result


def test_web_ppt_search_falls_back_to_direct_links_when_no_exact_ppt() -> None:
    from src.tools import web_research_service as svc

    rows = [
        {
            "title": "怎样制氢？氢能制取方法有哪些？一文带你全面了解",
            "url": "https://example.com/hydrogen-production",
            "snippet": "制氢 技术路线 天然气制氢 工艺介绍",
        },
        {
            "title": "Failure Analysis of a Cracked Hydrogen Reformer Tube",
            "url": "https://example.com/reformer-tube-failure",
            "snippet": "hydrogen reformer tube defects crack failure analysis",
        },
    ]

    with patch.object(svc, "_search_tavily_api", return_value=[]), \
         patch.object(svc, "_search_firecrawl_api", return_value=[]), \
         patch.object(svc, "_search_exa_api", return_value=[]), \
         patch.object(svc, "_search_brave_api", return_value=[]), \
         patch.object(svc, "_search_serpapi", return_value=[]), \
         patch.object(svc, "_search_searxng", return_value=[]), \
         patch.object(svc, "_search_bing_html", return_value=rows), \
         patch.object(svc, "_search_anysearch", return_value=[]):
        result = svc.web_ppt_search("制氢转化管缺陷 PPT PPTX 课件", max_results=5)

    assert "未找到可确认的高相关 PPT/PPTX/课件文件" in result
    assert "以下是继续保留的直接搜索结果" in result
    assert "Failure Analysis of a Cracked Hydrogen Reformer Tube" in result
    assert "怎样制氢" in result
    assert "Fallback direct results" in result


def test_web_ppt_search_uses_all_results_when_relevant_pool_only_has_bad_ppt() -> None:
    from src.tools import web_research_service as svc

    bad_ppt = [
        {
            "title": "氢的制储运加现状及趋势展望",
            "url": "https://example.com/hydrogen-general.pdf",
            "snippet": "PPT模板下载 氢能产业链 制氢 储运氢 加氢站",
        }
    ]
    direct_rows = [
        {
            "title": "怎样制氢？氢能制取方法有哪些？一文带你全面了解",
            "url": "https://example.com/hydrogen-production",
            "snippet": "制氢 技术路线 天然气制氢 工艺介绍",
        }
    ]

    with patch.object(svc, "_search_tavily_api", return_value=bad_ppt), \
         patch.object(svc, "_search_firecrawl_api", return_value=[]), \
         patch.object(svc, "_search_exa_api", return_value=[]), \
         patch.object(svc, "_search_brave_api", return_value=[]), \
         patch.object(svc, "_search_serpapi", return_value=[]), \
         patch.object(svc, "_search_searxng", return_value=[]), \
         patch.object(svc, "_search_bing_html", return_value=direct_rows), \
         patch.object(svc, "_search_anysearch", return_value=[]):
        result = svc.web_ppt_search("制氢转化管缺陷 PPT PPTX 课件", max_results=5)

    assert "以下是继续保留的直接搜索结果" in result
    assert "怎样制氢" in result
    assert "氢的制储运加现状及趋势展望" not in result


def test_ppt_query_variants_include_english_aliases() -> None:
    from src.tools import web_research_service as svc

    variants = svc._ppt_query_variants("制氢转化管缺陷 PPT PPTX 课件")

    assert any("hydrogen reformer tube defects failure analysis" in item for item in variants)
    assert any("powerpoint slides" in item for item in variants)


def test_firecrawl_search_api_parses_results() -> None:
    from src.tools import web_research_service as svc

    payload = {
        "success": True,
        "data": {
            "web": [
                {
                    "title": "Firecrawl Result",
                    "url": "https://example.com/firecrawl",
                    "description": "Open-Meteo API result",
                }
            ]
        },
    }

    with patch.object(svc, "FIRECRAWL_API_KEY", "firecrawl-test-key"), \
         patch("urllib.request.urlopen") as urlopen:
        response = urlopen.return_value.__enter__.return_value
        response.read.return_value = __import__("json").dumps(payload).encode("utf-8")
        rows = svc._search_firecrawl_api("Open-Meteo API", max_results=5)

    assert rows == [{
        "title": "Firecrawl Result",
        "url": "https://example.com/firecrawl",
        "snippet": "Open-Meteo API result",
    }]


def test_web_research_uses_aggregate_sources() -> None:
    from src.tools import web_research_service as svc

    rows = [{"title": "Result A", "url": "https://example.com/a", "snippet": "Snippet", "_source": "UnitSource"}]
    with patch.object(svc, "_aggregate_search_results", return_value=(rows, ["UnitSource: 1"])), \
         patch.object(svc, "web_read", return_value="网页正文：https://example.com/a\n读取方式：static\n\nReadable body"):
        result = svc.web_research("query", max_results=2, read_top=1)

    assert "UnitSource" in result
    assert "Readable body" in result
    assert "来源诊断" in result


def test_web_research_does_not_fall_back_to_unfiltered_search_when_aggregate_is_noise() -> None:
    from src.tools import web_research_service as svc

    with patch.object(svc, "_aggregate_search_results", return_value=([], ["Bing HTML: 10", "Relevance filter: kept 0/10"])), \
         patch.object(svc, "web_search", return_value="unfiltered noise") as web_search:
        result = svc.web_research("制氢转化管缺陷", max_results=10, read_top=2)

    assert "unfiltered noise" not in result
    assert "Relevance filter: kept 0/10" in result
    web_search.assert_not_called()


def test_web_research_skips_low_quality_blog_pages_for_body_reading() -> None:
    from src.tools import web_research_service as svc

    rows = [
        {"title": "Official", "url": "https://vendor.example/docs", "snippet": "official", "_source": "UnitSource"},
        {"title": "Blog mirror", "url": "https://blog.csdn.net/example/article/details/1", "snippet": "blog", "_source": "UnitSource"},
    ]

    def fake_read(url: str, **kwargs):
        if "vendor.example" in url:
            return "根据 robots.txt 规则，当前不抓取该页面：https://vendor.example/docs"
        raise AssertionError("low quality blog page should not be read")

    with patch.object(svc, "_aggregate_search_results", return_value=(rows, ["UnitSource: 2"])), \
         patch.object(svc, "web_read", side_effect=fake_read):
        result = svc.web_research("vendor docs", max_results=2, read_top=1)

    assert "Blog mirror" in result
    assert "low quality" not in result
    assert "来源诊断" in result


def test_bing_redirect_url_is_decoded() -> None:
    from src.tools import web_research_service as svc

    decoded = svc._decode_bing_url("https://www.bing.com/ck/a?u=a1aHR0cHM6Ly9leGFtcGxlLmNvbS9wYWdl")

    assert decoded == "https://example.com/page"


def test_web_read_extracts_text_and_respects_cache(tmp_path) -> None:
    from src.tools import web_research_service as svc

    html = "<html><head><title>x</title><script>bad()</script></head><body><article><h1>标题</h1><p>正文内容</p></article></body></html>"
    with patch.object(svc, "CACHE_DB", str(tmp_path / "cache.db")), \
         patch.object(svc, "_allowed_by_robots", return_value=True), \
         patch.object(svc, "_fetch_text", return_value=html) as fetch:
        first = svc.web_read("https://example.com/post", backend="static", max_chars=500)
        second = svc.web_read("https://example.com/post", backend="static", max_chars=500)

    assert "标题" in first
    assert "正文内容" in first
    assert "bad()" not in first
    assert second == first
    fetch.assert_called_once()


def test_web_read_uses_crawl4ai_backend_when_requested(tmp_path) -> None:
    from src.tools import web_research_service as svc

    with patch.object(svc, "CACHE_DB", str(tmp_path / "cache.db")), \
         patch.object(svc, "_allowed_by_robots", return_value=True), \
         patch.object(svc, "_fetch_crawl4ai", return_value="<article><h1>Crawl Title</h1><p>Crawl Body</p></article>") as crawl:
        result = svc.web_read("https://example.com/post", backend="crawl4ai", max_chars=500)

    assert "读取方式：crawl4ai" in result
    assert "Crawl Title" in result
    assert "Crawl Body" in result
    crawl.assert_called_once_with("https://example.com/post")


def test_web_read_uses_firecrawl_backend_when_requested(tmp_path) -> None:
    from src.tools import web_research_service as svc

    with patch.object(svc, "CACHE_DB", str(tmp_path / "cache.db")), \
         patch.object(svc, "ENABLE_FIRECRAWL", True), \
         patch.object(svc, "FIRECRAWL_API_KEY", "test-key"), \
         patch.object(svc, "_allowed_by_robots", return_value=True), \
         patch.object(svc, "_fetch_firecrawl", return_value="# Firecrawl Title\n\nFirecrawl body") as firecrawl:
        result = svc.web_read("https://example.com/post", backend="firecrawl", max_chars=500)

    assert "读取方式：firecrawl" in result
    assert "Firecrawl Title" in result
    assert "Firecrawl body" in result
    firecrawl.assert_called_once_with("https://example.com/post")


def test_web_read_auto_prefers_firecrawl_when_configured(tmp_path) -> None:
    from src.tools import web_research_service as svc

    with patch.object(svc, "CACHE_DB", str(tmp_path / "cache.db")), \
         patch.object(svc, "ENABLE_FIRECRAWL", True), \
         patch.object(svc, "FIRECRAWL_API_KEY", "test-key"), \
         patch.object(svc, "_allowed_by_robots", return_value=True), \
         patch.object(svc, "_fetch_firecrawl", return_value="# Auto Firecrawl") as firecrawl, \
         patch.object(svc, "_fetch_crawl4ai", return_value="# Crawl4AI") as crawl:
        result = svc.web_read("https://example.com/post", backend="auto", max_chars=500)

    assert "读取方式：firecrawl" in result
    assert "Auto Firecrawl" in result
    firecrawl.assert_called_once()
    crawl.assert_not_called()


def test_web_read_playwright_disabled_falls_back_to_static(tmp_path) -> None:
    from src.tools import web_research_service as svc

    html = "<html><body><p>Static fallback body</p></body></html>"

    with patch.object(svc, "CACHE_DB", str(tmp_path / "cache.db")), \
         patch.object(svc, "ENABLE_PLAYWRIGHT", False), \
         patch.object(svc, "_allowed_by_robots", return_value=True), \
         patch.object(svc, "_fetch_text", return_value=html):
        result = svc.web_read("https://example.com/dynamic", backend="playwright", max_chars=500)

    assert "读取方式：static fallback" in result
    assert "Static fallback body" in result


def test_web_read_jina_reader_backend(tmp_path) -> None:
    from src.tools import web_research_service as svc

    with patch.object(svc, "CACHE_DB", str(tmp_path / "cache.db")), \
         patch.object(svc, "_allowed_by_robots", return_value=True), \
         patch.object(svc, "_fetch_text_with_headers", return_value="Title: Example\n\nMarkdown Content:\nJina body") as fetch:
        result = svc.web_read("https://example.com/post", backend="jina_reader", max_chars=500)

    assert "读取方式：jina_reader" in result
    assert "Jina body" in result
    assert fetch.call_args.args[0] == "https://r.jina.ai/https://example.com/post"


def test_discover_public_sources_finds_feed_and_sitemap() -> None:
    from src.tools import web_research_service as svc

    def fake_fetch(url: str) -> str:
        if url.endswith("/robots.txt"):
            return "Sitemap: https://example.com/sitemap.xml\n"
        return '<html><link rel="alternate" type="application/rss+xml" href="/feed.xml"></html>'

    with patch.object(svc, "_fetch_text", side_effect=fake_fetch):
        result = svc.discover_public_sources("https://example.com", max_items=5)

    assert "https://example.com/sitemap.xml" in result
    assert "https://example.com/feed.xml" in result


def test_random_public_info_falls_back_to_search_when_wikipedia_random_fails() -> None:
    from src.tools import web_research_service as svc

    with patch.object(svc, "_fetch_text", side_effect=RuntimeError("network")), \
         patch.object(svc, "web_search", return_value="search fallback"):
        result = svc.random_public_info(count=1)

    assert "随机公共信息发现" in result
    assert "search fallback" in result


def test_paged_aggregate_results_include_urls_and_clickable_more_link(monkeypatch) -> None:
    from src.tools import web_research_service as svc

    monkeypatch.setenv("ANT_COLONY_PUBLIC_BASE_URL", "http://public.example")
    rows = [
        {
            "title": f"Topic Result {idx}",
            "url": f"https://example.com/{idx}",
            "snippet": "Topic result snippet",
            "_source": "Tavily",
        }
        for idx in range(1, 4)
    ]

    result = svc._format_aggregate_page_results(
        "topic",
        rows[:2],
        [],
        total_count=3,
        page=1,
        page_size=2,
        has_more=True,
        start_index=1,
    )

    assert "https://example.com/1" in result
    assert "https://example.com/2" in result
    assert "查看更多结果（第 2 页）" in result
    assert "http://public.example/api/v1/web-search/more?q=topic&page=2&page_size=2" in result


def test_paged_aggregate_more_link_is_before_wecom_markdown_limit(monkeypatch) -> None:
    from src.tools import web_research_service as svc

    monkeypatch.setenv("ANT_COLONY_PUBLIC_BASE_URL", "http://public.example")
    rows = [
        {
            "title": f"Long Topic Result {idx}",
            "url": f"https://example.com/{idx}",
            "snippet": "Long snippet " * 80,
            "_source": "Tavily",
        }
        for idx in range(1, 21)
    ]

    result = svc._format_aggregate_page_results(
        "long topic",
        rows,
        [],
        total_count=80,
        page=1,
        page_size=20,
        has_more=True,
        start_index=1,
    )

    more_pos = result.find("/api/v1/web-search/more?")
    assert more_pos != -1
    assert more_pos < 4000


def test_paged_aggregate_includes_page_link_even_without_next_page(monkeypatch) -> None:
    from src.tools import web_research_service as svc

    monkeypatch.setenv("ANT_COLONY_PUBLIC_BASE_URL", "http://public.example")
    rows = [
        {
            "title": f"Topic Result {idx}",
            "url": f"https://example.com/{idx}",
            "snippet": "Topic result snippet",
            "_source": "Tavily",
        }
        for idx in range(1, 21)
    ]

    result = svc._format_aggregate_page_results(
        "topic",
        rows,
        [],
        total_count=20,
        page=1,
        page_size=20,
        has_more=False,
        start_index=1,
    )

    assert "打开网页查看本页结果" in result
    assert "http://public.example/api/v1/web-search/more?q=topic&page=1&page_size=20" in result
    assert "查看更多结果（第 2 页）" not in result


def test_paged_aggregate_next_page_uses_cache_without_research(tmp_path, monkeypatch) -> None:
    from src.tools import web_research_service as svc

    monkeypatch.setattr(svc, "PAGE_CACHE_DIR", str(tmp_path / "page-cache"))
    rows = [
        {
            "title": f"Topic Result {idx}",
            "url": f"https://example.com/{idx}",
            "snippet": "Topic result snippet",
            "_source": "Tavily",
        }
        for idx in range(1, 26)
    ]
    svc._write_search_page_cache("topic", rows, ["Tavily: 25"])

    with patch.object(svc, "_aggregate_search_results", side_effect=AssertionError("should not research")):
        result = svc.web_search_aggregate_page("topic", page=2, page_size=20, max_total=40)

    assert "21. Topic Result 21" in result
    assert "https://example.com/21" in result


def test_cached_page_can_render_first_page_without_research(tmp_path, monkeypatch) -> None:
    from src.tools import web_research_service as svc

    monkeypatch.setattr(svc, "PAGE_CACHE_DIR", str(tmp_path / "page-cache"))
    rows = [
        {
            "title": f"Topic Result {idx}",
            "url": f"https://example.com/{idx}",
            "snippet": "Topic result snippet",
            "_source": "Tavily",
        }
        for idx in range(1, 4)
    ]
    svc._write_search_page_cache("topic", rows, ["Tavily: 3"])

    with patch.object(svc, "_aggregate_search_results", side_effect=AssertionError("should not research")):
        result = svc.web_search_aggregate_page_cached("topic", page=1, page_size=20)

    assert "1. Topic Result 1" in result
    assert "https://example.com/1" in result


def test_builtin_web_research_tools_are_callable() -> None:
    from src.tools.builtin import _web_discover_sources_tool, _web_read_tool, _web_research_health_tool, _web_research_tool, _web_search_aggregate_tool

    with patch("src.tools.web_research_service.web_research", return_value="research") as research:
        assert _web_research_tool({"query": "topic"}) == "research"
    with patch("src.tools.web_research_service.web_search_aggregate", return_value="aggregate") as aggregate:
        assert _web_search_aggregate_tool({"query": "topic"}) == "aggregate"
    with patch("src.tools.web_research_service.web_research_health", return_value="health") as health:
        assert _web_research_health_tool({}) == "health"
    with patch("src.tools.web_research_service.web_read", return_value="read") as read:
        assert _web_read_tool({"url": "https://example.com"}) == "read"
    with patch("src.tools.web_research_service.discover_public_sources", return_value="sources") as discover:
        assert _web_discover_sources_tool({"url": "https://example.com"}) == "sources"

    research.assert_called_once()
    aggregate.assert_called_once()
    health.assert_called_once()
    read.assert_called_once()
    discover.assert_called_once()
