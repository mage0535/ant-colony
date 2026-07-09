from __future__ import annotations

import re
from dataclasses import asdict
from dataclasses import dataclass
from typing import Any

from src.knowledge.collector import KnowledgeCollector
from src.knowledge.repository_factory import build_knowledge_repository
from src.memory.scoped_store import ScopedMemoryStore
from src.models.contracts import MessageContext
from src.platform import build_capability_context, invoke_capability, invoke_capability_first
from src.platform.role_manager import select_role
from src.store.database import Database


def _context_dict(user_id: str, context: MessageContext) -> dict[str, Any]:
    return asdict(build_capability_context(
        user_id=user_id,
        platform=str(context.metadata.get("provider") or context.metadata.get("platform") or "wecom"),
        transport=str(context.metadata.get("transport") or ""),
        scope=context.space_type.value if hasattr(context.space_type, "value") else str(context.space_type),
        scope_id=context.space_id,
        source_chat_id=str(context.metadata.get("source_chat_id") or ""),
        metadata=dict(context.metadata or {}),
    ))


def _default_owner(user_id: str, context: MessageContext) -> tuple[str, str]:
    from src.knowledge.acl import default_write_scope, resolve_role

    platform = str(context.metadata.get("provider") or context.metadata.get("platform") or "wecom")
    role = resolve_role(user_id, context.project_id or context.dept_id or context.space_id, platform=platform)
    return default_write_scope(role, user_id, platform=platform)


def _record_artifacts(user_id: str, context: MessageContext, title: str, content: str, source: str) -> None:
    conn = Database.get().connect()
    store = ScopedMemoryStore(conn)
    scope_type = "personal"
    scope_id = user_id
    if context.project_id:
        scope_type, scope_id = "project", context.project_id
    elif context.dept_id:
        scope_type, scope_id = "department", context.dept_id
    store.retain(f"{title}\n\n{content}", scope_type=scope_type, scope_id=scope_id, source=source)

    owner_type, owner_id = _default_owner(user_id, context)
    collector = KnowledgeCollector(build_knowledge_repository())
    collector.collect_text(content, title, owner_type=owner_type, owner_id=owner_id, tags=["workflow", source])


def _role_prefix(query: str) -> str:
    role = select_role(query)["role"]
    return f"【已启用专家角色：{role.name}】\n"


def _extract_workorder_id(text: str) -> str:
    match = re.search(r"(?:工单|工号|单号|订单)[：: ]*([A-Za-z0-9_-]{3,})", text)
    if match:
        return match.group(1)
    generic = re.search(r"\b([A-Z]{2,}-\d{2,}|WO-\d+)\b", text)
    return generic.group(1) if generic else ""


def _clean_capability_text(text: str, fallback: str) -> str:
    normalized = (text or "").strip()
    if not normalized:
        return fallback
    lowered = normalized.lower()
    if "http error 404" in lowered or "not found" in lowered:
        return fallback
    if "not configured" in lowered or "missing env var" in lowered:
        return fallback
    return normalized


def _workorder_reference(query: str, text: str) -> str:
    normalized = (text or "").strip()
    if not normalized:
        return "未找到相关资料"
    if any(marker in normalized for marker in ("工单", "作业", "维修", "异常", "设备", "SOP", "流程")):
        return normalized
    workorder_id = _extract_workorder_id(query)
    if workorder_id and workorder_id in normalized:
        return normalized
    return "未找到相关资料"


@dataclass(slots=True)
class WorkflowResult:
    title: str
    content: str


def _enterprise_next_steps(query: str) -> str:
    from src.platform.enterprise_query import plan_enterprise_query

    plan = plan_enterprise_query(query)
    if plan.domains == ("meeting_room",):
        return (
            "【下一步建议】\n"
            "1. 可继续指定日期和时间段查询会议室占用情况。\n"
            "2. 如果提示权限不足，需要给 AI 助手应用补充会议室、会议和日程读取权限。\n"
            "3. 确认空闲时段后，可以继续发起预订操作。"
        )
    if plan.domains == ("approval",):
        return (
            "【下一步建议】\n"
            "1. 可继续提供审批名称或审批编号查询当前节点。\n"
            "2. 如果提示权限不足，需要给 AI 助手应用补充审批数据读取权限。\n"
            "3. 催办、撤回或同意等写操作会在执行前再次确认。"
        )
    return (
        "【下一步建议】\n"
        "1. 可继续指定应用、对象和时间范围缩小查询。\n"
        "2. 跨应用汇总只会包含当前用户有权访问且已接入接口的数据。\n"
        "3. 写操作会在执行前校验权限并再次确认。"
    )


class OfficeWorkflowService:
    def enterprise_app_query(self, user_id: str, query: str, context: MessageContext) -> WorkflowResult:
        cap_ctx = _context_dict(user_id, context)
        from src.platform.enterprise_query_service import execute_enterprise_query

        app_data = _clean_capability_text(
            execute_enterprise_query(query, cap_ctx),
            "暂未查询到企业应用数据。可能原因是对应应用未授权给当前 AI 助手，或该应用没有当前条件下的数据。",
        )
        body = (
            _role_prefix(query or "企业应用查询")
            + f"【企业应用查询结果】\n{app_data}\n\n"
        )
        body += _enterprise_next_steps(query)
        _record_artifacts(user_id, context, "企业应用查询结果", body, "enterprise_app_query")
        return WorkflowResult("企业应用查询结果", body)

    def approval_followup(self, user_id: str, query: str, context: MessageContext) -> WorkflowResult:
        cap_ctx = _context_dict(user_id, context)
        approvals = _clean_capability_text(invoke_capability("approval.list", "pending", context=cap_ctx, empty_message=""), "暂无审批列表能力")
        detail = _clean_capability_text(invoke_capability_first("approval.detail", query or "pending", context=cap_ctx, empty_message=""), "暂无审批详情能力")
        docs = _clean_capability_text(invoke_capability_first("docs.read", query, context=cap_ctx, empty_message=""), "未找到相关文档")
        mail = _clean_capability_text(invoke_capability("mail.summary", query, context=cap_ctx, empty_message=""), "暂无相关邮件")
        body = (
            _role_prefix(query or "审批跟踪")
            + f"【审批待办】\n{approvals or '暂无待办'}\n\n"
            + f"【审批详情】\n{detail or '暂无详情'}\n\n"
            + f"【相关文档】\n{docs or '未找到相关文档'}\n\n"
            + f"【相关邮件摘要】\n{mail or '暂无相关邮件'}\n\n"
            + "【下一步建议】\n1. 先确认审批当前节点和卡点原因。\n2. 如果缺材料，直接整理补件清单。\n3. 如需催办，可生成催办消息或发起会议。"
        )
        _record_artifacts(user_id, context, "审批跟踪结果", body, "approval_followup")
        return WorkflowResult("审批跟踪结果", body)

    def meeting_coordination(self, user_id: str, query: str, context: MessageContext) -> WorkflowResult:
        cap_ctx = _context_dict(user_id, context)
        agenda = _clean_capability_text(invoke_capability("calendar.list", 7, context=cap_ctx, empty_message=""), "暂无日程能力")
        meetings = _clean_capability_text(invoke_capability("meeting.list", context=cap_ctx, empty_message=""), "暂无会议能力")
        docs = _clean_capability_text(invoke_capability_first("docs.read", query, context=cap_ctx, empty_message=""), "未找到相关资料")
        body = (
            _role_prefix(query or "会议组织")
            + f"【近期日程】\n{agenda or '暂无日程'}\n\n"
            + f"【近期会议】\n{meetings or '暂无会议'}\n\n"
            + f"【参考资料】\n{docs or '未找到相关资料'}\n\n"
            + "【建议动作】\n1. 明确会议主题、参会人和时间。\n2. 确认后可直接创建会议。\n3. 会后可继续让我整理纪要和行动项。"
        )
        _record_artifacts(user_id, context, "会议组织建议", body, "meeting_coordination")
        return WorkflowResult("会议组织建议", body)

    def policy_drafting(self, user_id: str, query: str, context: MessageContext) -> WorkflowResult:
        cap_ctx = _context_dict(user_id, context)
        docs = _clean_capability_text(invoke_capability("docs.search", query, context=cap_ctx, empty_message=""), "未找到模板或参考资料")
        knowledge = _clean_capability_text(invoke_capability_first("drive.read", query, context=cap_ctx, empty_message=""), "暂无参考内容")
        body = (
            _role_prefix(query or "制度起草")
            + f"【参考文档】\n{docs or '暂无参考文档'}\n\n"
            + f"【参考内容】\n{knowledge or '暂无参考内容'}\n\n"
            + "【起草建议】\n1. 先确认文种：制度 / 办法 / 通知 / 周报。\n2. 再确认适用范围、条目清单和口吻。\n3. 如已有模板，可直接继续发要求生成正式文档。"
        )
        _record_artifacts(user_id, context, "制度起草建议", body, "policy_drafting")
        return WorkflowResult("制度起草建议", body)

    def workorder_analysis(self, user_id: str, query: str, context: MessageContext) -> WorkflowResult:
        cap_ctx = _context_dict(user_id, context)
        workorder_id = _extract_workorder_id(query) or query.strip()
        detail = _clean_capability_text(invoke_capability_first("ops.workorder.lookup", workorder_id, context=cap_ctx, empty_message=""), "未找到工单")
        analysis = _clean_capability_text(invoke_capability_first("ops.workorder.analyze", workorder_id, context=cap_ctx, empty_message=""), "暂无工单分析")
        docs = _workorder_reference(query, invoke_capability_first("docs.read", query, context=cap_ctx, empty_message=""))
        body = (
            _role_prefix(query or "工单分析")
            + f"【工单详情】\n{detail or '未找到工单'}\n\n"
            + f"【工单分析】\n{analysis or '暂无分析'}\n\n"
            + f"【相关知识】\n{docs or '未找到相关资料'}\n\n"
            + "【建议动作】\n1. 判断是否为超时、卡料、待审批或待确认。\n2. 如需跟进，可创建任务并通知负责人。\n3. 如需汇报，可继续让我生成异常说明或周报摘要。"
        )
        _record_artifacts(user_id, context, "工单分析结果", body, "workorder_analysis")
        return WorkflowResult("工单分析结果", body)
