from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class EnterpriseQueryPlan:
    original_query: str
    domains: tuple[str, ...] = ()
    operation: str = "query"
    entities: tuple[str, ...] = ()
    query_terms: tuple[str, ...] = ()
    start_date: str = ""
    end_date: str = ""
    user_scope: str = "authorized"
    cross_domain: bool = False


_DOMAIN_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("meeting_room", ("会议室", "会义室", "会议房间")),
    ("approval", ("审批", "申批", "审批流", "流程状态", "待办")),
    ("meeting", ("会议", "参会")),
    ("calendar", ("日程", "日历", "安排")),
    ("docs", ("在线文档", "文档")),
    ("drive", ("网盘", "云盘")),
    ("mail", ("邮件", "邮箱")),
    ("contacts", ("通讯录", "联系人")),
    ("third_party", ("第三方应用", "业务系统", "工单", "订单")),
)
_CROSS_DOMAIN_WORDS = ("汇总", "综合", "全部应用", "所有应用", "跨应用", "一起查")


def plan_enterprise_query(query: str) -> EnterpriseQueryPlan:
    normalized = _normalize(query)
    cross_domain = any(word in normalized for word in _CROSS_DOMAIN_WORDS)
    domains = _match_domains(normalized)
    if not cross_domain and domains:
        domains = domains[:1]

    operation = "query"
    if domains == ("meeting_room",):
        if any(word in normalized for word in ("哪个", "哪些", "空闲", "可用", "可以申请", "能申请")):
            operation = "availability"
        else:
            operation = "occupancy"
    elif domains == ("approval",):
        operation = "status" if any(word in normalized for word in ("到哪", "进度", "卡在")) else "list"

    entities: tuple[str, ...] = ()
    if "meeting_room" in domains and operation != "availability":
        room = _extract_room_name(normalized)
        if room:
            entities = (room,)

    query_terms = _extract_query_terms(normalized, domains)
    today = date.today().isoformat() if "今天" in normalized else ""
    user_scope = "self" if re.search(r"(?:^|查询|查|看)(?:一下)?我|我的|本人", normalized) else "authorized"
    return EnterpriseQueryPlan(
        original_query=query,
        domains=domains,
        operation=operation,
        entities=entities,
        query_terms=query_terms,
        start_date=today,
        end_date=today,
        user_scope=user_scope,
        cross_domain=cross_domain,
    )


def _normalize(query: str) -> str:
    return re.sub(r"\s+", "", str(query or "").strip().lower())


def _match_domains(query: str) -> tuple[str, ...]:
    positioned: list[tuple[int, str]] = []
    for domain, aliases in _DOMAIN_ALIASES:
        positions = [query.find(alias) for alias in aliases if alias in query]
        if positions:
            positioned.append((min(positions), domain))
    positioned.sort(key=lambda item: item[0])
    matched = [domain for _, domain in positioned]
    if "meeting_room" in matched and "meeting" in matched:
        matched.remove("meeting")
    if not matched and "申请" in query and any(
        word in query for word in ("状态", "进度", "到哪", "查询", "查一下", "情况")
    ):
        matched.append("approval")
    return tuple(matched)


def _extract_room_name(query: str) -> str:
    match = re.search(r"([一二三四五六七八九十百0-9A-Za-z]+号?会议室)", query)
    return match.group(1) if match else ""


def _extract_query_terms(query: str, domains: tuple[str, ...]) -> tuple[str, ...]:
    cleaned = query
    for _, aliases in _DOMAIN_ALIASES:
        for alias in aliases:
            cleaned = cleaned.replace(alias, "")
    for word in (
        "查询",
        "查一下",
        "查",
        "看看",
        "我",
        "我的",
        "所有",
        "全部",
        "状态",
        "进度",
        "到哪了",
        "到哪",
        "目前",
        "是什么情况",
        "什么情况",
        "情况",
        "今天",
        "有人",
        "可以",
        "申请",
        "吗",
        "？",
        "?",
    ):
        cleaned = cleaned.replace(word, "")
    terms = [part for part in re.split(r"[，,、；;]+", cleaned) if len(part) >= 2]
    if not terms and domains == ("approval",):
        match = re.search(r"(.{2,20}?)(?:申请|申批)", query)
        if match:
            terms.append(match.group(1))
    return tuple(dict.fromkeys(terms))
