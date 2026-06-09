from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

_ROLE_HINTS: list[tuple[list[str], str]] = [
    (["上线", "部署", "CI", "CD", "发布", "运维", "集群", "监控", "告警", "服务器", "回滚"], "运维工程师"),
    (["需求", "产品", "功能", "体验", "用户", "交互", "PRD", "原型", "用研"], "产品经理"),
    (["测试", "bug", "BUG", "复现", "用例", "回归", "验收", "冒烟", "单测", "单元测试"], "测试工程师"),
    (["前端", "UI", "界面", "CSS", "组件", "渲染", "页面", "样式", "JS", "HTML", "vue", "react"], "前端工程师"),
    (["后端", "API", "数据库", "接口", "服务", "缓存", "SQL", "事务", "中间件", "K/V", "微服务"], "后端工程师"),
    (["架构", "设计", "方案", "重构", "技术选型", "评审", "领域模型", "DDD"], "架构师"),
    (["数据", "分析", "报表", "指标", "看板", "ETL", "数仓", "埋点", "数分"], "数据工程师"),
    (["安全", "漏洞", "渗透", "审计", "加密", "认证", "授权", "鉴权"], "安全工程师"),
    (["运营", "活动", "推广", "转化", "留存", "拉新", "促活", "DAU", "MAU", "流量"], "运营"),
]


def _extract_word_freqs(text: str, top_n: int = 5) -> list[str]:
    bigrams: dict[str, int] = {}
    chars = list(text)
    for i in range(len(chars) - 1):
        ch1, ch2 = chars[i], chars[i + 1]
        if "\u4e00" <= ch1 <= "\u9fff" and "\u4e00" <= ch2 <= "\u9fff":
            bg = ch1 + ch2
            bigrams[bg] = bigrams.get(bg, 0) + 1

    en_words = re.findall(r"[a-zA-Z]{2,}", text)
    for w in en_words:
        wl = w.lower()
        bigrams[wl] = bigrams.get(wl, 0) + 1

    _stop = {"一个", "这个", "我们", "他们", "可以", "需要", "已经", "不是", "没有", "什么",
             "the", "of", "to", "is", "in", "and", "for", "are"}
    filtered = [(w, c) for w, c in bigrams.items() if w.lower() not in _stop and len(w) >= 2]
    filtered.sort(key=lambda x: -x[1])
    return [w for w, _ in filtered[:top_n]]


class RoleAnalyzer:
    """Scans memory files to build an in-memory role cache.

    Memory files follow the pattern ``{memory_dir}/{namespace}_{user_id}.json``
    as created by ``SidecarMemory``.
    """

    def __init__(self, memory_dir: str = "", namespace: str = "agent") -> None:
        self.memory_dir = memory_dir or os.environ.get("ANT_COLONY_MEMORY_DIR", "./data/memory")
        self.namespace_prefix = f"{namespace}_"
        self._cache: dict[str, dict[str, Any]] = {}
        self.reload()

    def reload(self) -> None:
        self._cache.clear()
        try:
            for fname in os.listdir(self.memory_dir):
                if not fname.endswith(".json"):
                    continue
                if not fname.startswith(self.namespace_prefix):
                    continue
                user_id = fname[len(self.namespace_prefix):-len(".json")]
                fpath = os.path.join(self.memory_dir, fname)
                try:
                    with open(fpath, encoding="utf-8") as f:
                        data = json.load(f)
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("RoleAnalyzer failed to load %s: %s", fpath, e)
                    continue
                entry: dict[str, Any] = {}
                for key in ("role", "department", "responsibilities", "preferences"):
                    if key in data:
                        entry[key] = data[key]
                if entry:
                    self._cache[user_id] = entry
        except OSError as e:
            logger.warning("RoleAnalyzer cannot scan %s: %s", self.memory_dir, e)
        logger.info("RoleAnalyzer loaded %d role entries", len(self._cache))

    def get_role(self, user_id: str) -> dict[str, Any] | None:
        return self._cache.get(user_id)

    def guess_role(self, sender_id: str, content: str) -> dict[str, Any]:
        cached = self.get_role(sender_id)
        if cached:
            return dict(cached)
        content_lower = content.lower() if content else ""
        for keywords, role in _ROLE_HINTS:
            for kw in keywords:
                if kw in content or kw.lower() in content_lower:
                    return {"role": role, "department": "", "_guessed": True}
        return {"role": "未知", "department": "", "_guessed": True}


class GroupMessageAnalyzer:
    """Analyzes group chat messages to compute role distribution."""

    def __init__(self, role_analyzer: RoleAnalyzer) -> None:
        self.role_analyzer = role_analyzer

    def analyze(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        user_stats: dict[str, dict[str, Any]] = {}
        for msg in messages:
            uid = msg.get("from_user_id", "") or ""
            content = msg.get("content", "") or ""
            ri = self.role_analyzer.guess_role(uid, content)
            if uid not in user_stats:
                user_stats[uid] = {
                    "user_id": uid,
                    "role": ri.get("role", "未知"),
                    "dept": ri.get("department", ""),
                    "message_count": 0,
                }
            user_stats[uid]["message_count"] += 1
        return list(user_stats.values())

    def summarize(self, messages: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        role_msgs: dict[str, list[str]] = {}
        role_users: dict[str, set[str]] = {}

        for msg in messages:
            uid = msg.get("from_user_id", "") or ""
            content = msg.get("content", "") or ""
            ri = self.role_analyzer.guess_role(uid, content)
            role = ri.get("role", "未知")
            role_msgs.setdefault(role, []).append(content)
            role_users.setdefault(role, set()).add(uid)

        result: dict[str, dict[str, Any]] = {}
        for role, contents in role_msgs.items():
            topics = _extract_word_freqs(" ".join(contents))
            result[role] = {
                "count": len(contents),
                "users": sorted(role_users[role]),
                "key_topics": topics,
            }
        return result
