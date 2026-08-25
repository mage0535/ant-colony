from __future__ import annotations

from datetime import datetime
from typing import Any

from src.platform.application_registry import get_application_domain
from src.platform.enterprise_query import EnterpriseQueryPlan, plan_enterprise_query


_DOMAIN_LABELS = {
    "meeting_room": "会议室",
    "meeting": "会议",
    "approval": "审批",
    "calendar": "日程",
    "docs": "在线文档",
    "drive": "网盘",
    "mail": "邮箱",
    "contacts": "通讯录",
    "third_party": "第三方应用",
}


def execute_enterprise_query(query: str, context: dict[str, Any] | None = None) -> str:
    from src.platform import invoke_capability

    plan = plan_enterprise_query(query)
    if not plan.domains:
        return ""
    sections: list[str] = []
    for domain in plan.domains:
        application = get_application_domain(domain)
        if application is None:
            continue
        args = _capability_args(plan, domain)
        result = invoke_capability(
            application.capability_id,
            *args,
            context=context,
            empty_message="",
        )
        if result:
            sections.append(f"【{_DOMAIN_LABELS.get(domain, domain)}】\n{result}")
    if not sections:
        return ""
    return "\n\n".join(sections) + f"\n\n查询时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"


def _capability_args(plan: EnterpriseQueryPlan, domain: str) -> tuple[Any, ...]:
    if domain in {"meeting_room", "approval", "docs", "drive", "mail", "contacts", "third_party"}:
        return (plan.original_query,)
    if domain == "calendar":
        return (7,)
    return ()
