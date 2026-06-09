"""Role Manager — AI expert role selection based on conversation context.

Loads 215 expert role definitions from agency-agents-zh, auto-selects
the best matching role for the user's needs, and injects role-specific
instructions into the Agent's context.

Roles are stored in `data/roles/` directory, organized by category.
Fallback built-in catalog covers the most common roles.

Usage::

    from src.platform.role_manager import select_role, get_role, list_roles
    role = select_role("帮我写一篇小红书种草笔记")
    # → Role(name="小红书运营专家", category="marketing", ...)
    content = role.content  # Markdown role definition
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

ROLES_DIR = os.environ.get("ROLES_DIR", "./data/roles")
MAX_CACHE = 200  # max cached role content strings


@dataclass
class Role:
    name: str = ""
    category: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    filepath: str = ""
    content: str = ""


# Built-in minimal catalog (full definitions loaded from files)
BUILTIN_CATALOG: list[dict[str, Any]] = [
    # Engineering
    {"name": "前端开发者", "category": "engineering", "tags": ["react","vue","ui","web","css","javascript","typescript"]},
    {"name": "后端架构师", "category": "engineering", "tags": ["api","database","microservice","architecture","server"]},
    {"name": "AI工程师", "category": "engineering", "tags": ["machine learning","deep learning","model","pipeline"]},
    {"name": "DevOps自动化师", "category": "engineering", "tags": ["ci/cd","docker","kubernetes","infrastructure"]},
    {"name": "安全工程师", "category": "engineering", "tags": ["security","owasp","audit","vulnerability","pentest"]},
    {"name": "代码审查员", "category": "engineering", "tags": ["code review","quality","pr","best practices"]},
    {"name": "软件架构师", "category": "engineering", "tags": ["system design","ddd","architecture decision"]},
    {"name": "技术文档工程师", "category": "engineering", "tags": ["documentation","api docs","technical writing"]},
    {"name": "微信小程序开发者", "category": "engineering", "tags": ["wechat","mini program","wxml","wxss"]},
    {"name": "飞书集成开发工程师", "category": "engineering", "tags": ["feishu","lark","robot","bitable"]},
    {"name": "钉钉集成开发工程师", "category": "engineering", "tags": ["dingtalk","robot","connector"]},
    # Design
    {"name": "UI设计师", "category": "design", "tags": ["visual design","component","design system","figma"]},
    {"name": "UX架构师", "category": "design", "tags": ["information architecture","interaction","navigation"]},
    {"name": "品牌守护者", "category": "design", "tags": ["brand","identity","visual identity"]},
    # Marketing (China)
    {"name": "小红书运营专家", "category": "marketing", "tags": ["xiaohongshu","种草","笔记","达人","爆款"]},
    {"name": "抖音策略师", "category": "marketing", "tags": ["douyin","短视频","直播","算法"]},
    {"name": "微信公众号运营", "category": "marketing", "tags": ["wechat","公众号","社群","裂变"]},
    {"name": "B站内容策略师", "category": "marketing", "tags": ["bilibili","up主","中长视频"]},
    {"name": "百度SEO专家", "category": "marketing", "tags": ["baidu","seo","搜索优化","百科"]},
    {"name": "私域流量运营师", "category": "marketing", "tags": ["私域","SCRM","社群运营","复购"]},
    {"name": "跨境电商运营专家", "category": "marketing", "tags": ["amazon","shopee","跨境","出海"]},
    {"name": "中国电商运营专家", "category": "marketing", "tags": ["淘宝","拼多多","京东","电商"]},
    {"name": "内容创作者", "category": "marketing", "tags": ["content","copywriting","blog","social media"]},
    {"name": "增长黑客", "category": "marketing", "tags": ["growth","acquisition","viral","experiment"]},
    {"name": "SEO专家", "category": "marketing", "tags": ["google","seo","search","organic"]},
    # Product
    {"name": "产品经理", "category": "product", "tags": ["product","prd","roadmap","strategy"]},
    {"name": "趋势研究员", "category": "product", "tags": ["research","competitive analysis","market"]},
    # Sales
    {"name": "客户拓展策略师", "category": "sales", "tags": ["account","abm","key account"]},
    {"name": "售前工程师", "category": "sales", "tags": ["presales","demo","technical solution"]},
    # HR
    {"name": "招聘专家", "category": "hr", "tags": ["recruiting","hiring","interview","boss直聘"]},
    {"name": "绩效管理专家", "category": "hr", "tags": ["performance","okr","kpi","review"]},
    # Finance
    {"name": "财务预测分析师", "category": "finance", "tags": ["financial","forecast","saas","cash flow"]},
    # Legal
    {"name": "合同审查专家", "category": "legal", "tags": ["contract","legal review","risk"]},
    # Supply Chain
    {"name": "供应链采购策略师", "category": "supply-chain", "tags": ["procurement","supplier","erp"]},
    # Testing
    {"name": "API测试员", "category": "testing", "tags": ["api test","integration","endpoint"]},
    {"name": "性能基准师", "category": "testing", "tags": ["performance","benchmark","load test"]},
    # Specialized
    {"name": "提示词工程师", "category": "specialized", "tags": ["prompt","llm","optimization"]},
    {"name": "政务数字化售前顾问", "category": "specialized", "tags": ["government","tog","信创","等保"]},
    {"name": "MCP构建器", "category": "specialized", "tags": ["mcp","server","tool","api"]},
    {"name": "医疗健康营销合规师", "category": "specialized", "tags": ["healthcare","medical","compliance","nmpa"]},
]

# Cache loaded roles
_role_cache: dict[str, str] = {}


def _load_role_file(name: str) -> str | None:
    """Load role content from file by exact name match."""
    if name in _role_cache:
        return _role_cache[name]
    # Search in ROLES_DIR
    base = ROLES_DIR
    if not os.path.isdir(base):
        return None
    for root, _dirs, files in os.walk(base):
        for f in files:
            if f.endswith(".md") and (name in f.replace(".md", "").replace("-", " ").replace("_", " ")):
                fp = os.path.join(root, f)
                try:
                    with open(fp, encoding="utf-8") as fh:
                        content = fh.read()
                    if len(_role_cache) < MAX_CACHE:
                        _role_cache[name] = content
                    return content
                except Exception as e:
                    logger.warning("Failed to load role %s from %s: %s", name, fp, e)
    return None


def search_roles(query: str, category: str = "", limit: int = 5) -> list[Role]:
    """Search roles by keyword. Returns ranked matches using intent + keyword scoring."""
    query_lower = query.lower()
    query_words = [w for w in re.findall(r'[\w\u4e00-\u9fff]+', query_lower) if len(w) > 1]

    # Intent keywords → category routing (strong signal)
    intent_map = {
        "代码": "engineering", "开发": "engineering", "算法": "engineering",
        "设计": "design", "UI": "design", "UX": "design", "界面": "design",
        "营销": "marketing", "推广": "marketing", "内容": "marketing", "种草": "marketing",
        "产品": "product", "审查": "engineering", "审计": "engineering",
        "测试": "testing", "招聘": "hr",
    }
    detected_category = category
    for kw, cat in intent_map.items():
        if kw.lower() in query_lower:
            detected_category = cat
            break

    scored: list[tuple[Role, int]] = []
    for entry in BUILTIN_CATALOG:
        if detected_category and entry["category"] != detected_category:
            continue
        if category and entry["category"] != category:
            continue
        role = Role(**entry)
        score = 0
        name_lower = role.name.lower()
        tag_text = " ".join(role.tags).lower()

        # Category match bonus
        if detected_category and entry["category"] == detected_category:
            score += 15

        # Tag substring matching (bidirectional)
        for qw in query_words:
            if qw in tag_text:
                score += 8
        for tag in role.tags:
            if tag.lower() in query_lower:
                score += 8

        # Name match
        for qw in query_words:
            if qw in name_lower:
                score += 12

        if score > 0:
            scored.append((role, score))

    scored.sort(key=lambda x: -x[1])
    return [r for r, _ in scored[:limit]]


def select_role(query: str) -> dict[str, Any]:
    """Auto-select the best matching role for the user's request.

    Returns::
        {"role": Role, "match_score": int, "matched_as": str}
    """
    results = search_roles(query, limit=3)
    if not results:
        return {
            "role": Role(name="通用助手", category="general", description="通用 AI 助手", tags=[]),
            "match_score": 0,
            "matched_as": "general",
        }
    best = results[0]
    # Try to load full role content from file
    content = _load_role_file(best.name)
    if content:
        best.content = content
    return {
        "role": best,
        "match_score": 10 + (10 if content else 0),
        "matched_as": best.name,
    }


def get_role(name: str) -> Role | None:
    """Get a role by exact name."""
    for entry in BUILTIN_CATALOG:
        if entry["name"] == name:
            role = Role(**entry)
            content = _load_role_file(name)
            if content:
                role.content = content
            return role
    return None


def list_roles(category: str = "") -> list[Role]:
    """List all available roles, optionally filtered by category."""
    entries = BUILTIN_CATALOG
    if category:
        entries = [e for e in entries if e["category"] == category]
    return [Role(**e) for e in entries]


def list_categories() -> list[str]:
    """List all role categories."""
    cats: set[str] = set()
    for e in BUILTIN_CATALOG:
        cats.add(e["category"])
    return sorted(cats)
