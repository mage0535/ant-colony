from __future__ import annotations



import json

from typing import Any



import logging

logger = logging.getLogger(__name__)

from src.tools.registry import ToolSpec
from src.tools.platform_capability_tools import (
    approval_detail_tool as _approval_detail_tool,
    approval_list_tool as _approval_list_tool,
    calendar_detail_tool as _calendar_detail_tool,
    calendar_create_tool as _calendar_create_tool,
    compress_pdf_tool as _compress_pdf_tool,
    create_doc_tool as _create_doc_tool,
    create_meeting_tool as _create_meeting_tool,
    enterprise_app_action_tool as _enterprise_app_action_tool,
    enterprise_app_query_tool as _enterprise_app_query_tool,
    edit_doc_content_tool as _edit_doc_content_tool,
    doc_search_tool as _doc_search_tool,
    read_docs_tool as _read_docs_tool,
    docx_template_outline_tool as _docx_template_outline_tool,
    drive_search_tool as _drive_search_tool,
    read_drive_tool as _read_drive_tool,
    extract_pdf_images_tool as _extract_pdf_images_tool,
    list_capabilities_tool as _list_capabilities_tool,
    list_meetings_tool as _list_meetings_tool,
    meeting_detail_tool as _meeting_detail_tool,
    mail_summary_tool as _mail_summary_tool,
    merge_pdfs_tool as _merge_pdfs_tool,
    ocr_pdf_tool as _ocr_pdf_tool,
    office_service_status_tool as _office_service_status_tool,
    pdf_service_status_tool as _pdf_service_status_tool,
    pptx_template_outline_tool as _pptx_template_outline_tool,
    protect_pdf_tool as _protect_pdf_tool,
    read_docx_tool as _read_docx_tool,
    read_pdf_tool as _read_pdf_tool,
    read_pptx_tool as _read_pptx_tool,
    read_xlsx_tool as _read_xlsx_tool,
    sheet_append_tool as _sheet_append_tool,
    smartpage_create_tool as _smartpage_create_tool,
    split_pdf_tool as _split_pdf_tool,
    todo_create_tool as _todo_create_tool,
    todo_list_tool as _todo_list_tool,
    todo_update_tool as _todo_update_tool,
    todo_user_search_tool as _todo_user_search_tool,
    watermark_pdf_tool as _watermark_pdf_tool,
    who_is_admin_tool as _who_is_admin_tool,
    who_is_leader_tool as _who_is_leader_tool,
    xlsx_template_outline_tool as _xlsx_template_outline_tool,
)
from src.tools.task_tools import (
    create_draft_tool as _create_draft_tool,
    list_spaces_tool as _list_spaces_tool,
    query_tasks_tool as _query_tasks_tool,
    search_tasks_tool as _search_tasks_tool,
    set_priority_tool as _set_priority_tool,
    task_analytics_tool as _task_analytics_tool,
    transition_task_tool as _transition_task_tool,
    work_journal_tool as _work_journal_tool,
)
from src.tools.knowledge_tools import (
    add_document_tool as _add_document_tool,
    delete_cloud_drive_tool as _delete_cloud_drive_tool,
    delete_knowledge_tool as _delete_knowledge_tool,
    import_company_guides_tool as _import_company_guides_tool,
    list_cloud_drives_tool as _list_cloud_drives_tool,
    list_knowledge_tool as _list_knowledge_tool,
    promote_knowledge_tool as _promote_knowledge_tool,
    register_cloud_drive_tool as _register_cloud_drive_tool,
    search_knowledge_tool as _search_knowledge_tool,
    sync_from_cloud_tool as _sync_from_cloud_tool,
    update_knowledge_tool as _update_knowledge_tool,
)
from src.tools.memory_scope_tools import (
    promote_scoped_memory_tool as _promote_scoped_memory_tool,
    write_scoped_memory_tool as _write_scoped_memory_tool,
)
from src.tools.org_admin_tools import (
    add_admin_tool as _add_admin_tool,
    attendance_tool as _attendance_tool,
    dept_attendance_tool as _dept_attendance_tool,
    leave_balance_tool as _leave_balance_tool,
    leave_tool as _leave_tool,
    remove_admin_tool as _remove_admin_tool,
    subordinate_balance_tool as _subordinate_balance_tool,
    subordinate_tool as _subordinate_tool,
)
from src.tools.email_capability_tools import (
    get_email_tool as _get_email_tool,
    list_emails_tool as _list_emails_tool,
    search_emails_tool as _search_emails_tool,
    send_email_tool as _send_email_tool,
)
from src.tools.role_methodology_tools import (
    investigate_tool as _investigate_tool,
    list_roles_tool as _list_roles_tool,
    office_hours_tool as _office_hours_tool,
    retro_tool as _retro_tool,
    review_doc_tool as _review_doc_tool,
    select_role_tool as _select_role_tool,
    set_role_tool as _set_role_tool,
    spec_tool_handler as _spec_tool,
)
from src.tools.workflow_assistant_tools import (
    approval_followup_workflow_tool as _approval_followup_workflow_tool,
    meeting_coordination_workflow_tool as _meeting_coordination_workflow_tool,
    policy_drafting_workflow_tool as _policy_drafting_workflow_tool,
    workorder_analysis_workflow_tool as _workorder_analysis_workflow_tool,
)
from src.tools.document_prompt_helpers import (
    build_policy_fallback_content_helper as _build_policy_fallback_content,
    build_requirement_spec_helper as _build_requirement_spec,
    build_template_excerpt_helper as _build_template_excerpt,
    build_template_prompt_block_helper as _build_template_prompt_block,
    canonical_policy_section_heading_helper as _canonical_policy_section_heading,
    formalize_policy_item_helper as _formalize_policy_item,
    formalize_policy_spec_item_helper as _formalize_policy_spec_item,
    is_policy_primary_item_helper as _is_policy_primary_item,
    is_policy_section_heading_helper as _is_policy_section_heading,
    is_policy_sub_item_helper as _is_policy_sub_item,
    normalize_request_lines_helper as _normalize_request_lines,
    split_template_and_request_helper as _split_template_and_request,
    strip_policy_marker_helper as _strip_policy_marker,
)
from src.tools.basic_tool_modules import (
    calendar_agenda_tool as _calendar_agenda_tool,
    contact_search_tool as _contact_search_tool,
    ddg_search_tool as _ddg_search_tool,
    echo_tool as _echo_tool,
    humanize_tool as _humanize_tool,
    now_tool as _now_tool,
    tushare_tool as _tushare_tool,
)










def _extract_policy_sections(request_text: str) -> list[tuple[str, list[str]]]:
    spec = _build_requirement_spec('', '', request_text)
    return [
        (section['raw_title'], [item['main'] for item in section['items']])
        for section in spec['sections']
    ]


def _generate_report_handler(args):
    from src.tools.document_generation_service import generate_document

    return generate_document(args)










def _get_entry_link_tool(args: dict[str, Any]) -> str:
    target = str(args.get("target", "menu")).strip().lower()
    user_id = str(args.get("user_id") or args.get("from") or "")
    platform = str(args.get("platform", "") or args.get("_source_provider", "")) or "wecom"
    from src.gateway.entry_links import _admin_reply, _knowledge_reply, _menu_reply

    if target == "admin":
        from src.web.admin_auth import is_hr_specialist, is_platform_admin
        if not (is_platform_admin(platform, user_id) or is_hr_specialist(platform, user_id)):
            return "你当前没有管理员或人事专员权限，不能打开后台控制台。你可以发送「打开知识库」进入自己的知识库管理页面。"
        return _admin_reply(platform, user_id)
    if target == "knowledge":
        return _knowledge_reply(platform, user_id)
    return _menu_reply(platform, user_id)


def _broadcast_org_message_tool(args: dict[str, Any]) -> str:
    platform = str(args.get("platform", "") or args.get("_source_provider", "")) or "wecom"
    user_id = str(args.get("user_id") or args.get("from") or args.get("sender_user_id") or "")
    target = str(args.get("target") or args.get("scope") or args.get("department") or "")
    message = str(args.get("message") or args.get("text") or args.get("content") or "")
    from src.web.admin_auth import is_platform_admin

    if not is_platform_admin(platform, user_id):
        return "你当前没有管理员权限，不能向组织架构群发通知。"
    try:
        from src.platform.organization_broadcast_service import broadcast_to_organization

        result = broadcast_to_organization(
            platform=platform,
            sender_user_id=user_id,
            target=target,
            message=message,
        )
    except Exception as exc:
        return f"组织通知发送失败：{exc}"

    failed = int(result.get("failed", 0) or 0)
    if failed:
        return (
            f"组织通知已部分发送：目标「{target}」，已发送 {result.get('sent', 0)} 人，"
            f"失败 {failed} 人，跳过 {result.get('skipped', 0)} 人。"
        )
    return (
        f"组织通知已发送：目标「{target}」，已发送 {result.get('sent', 0)} 人，"
        f"跳过未开通或暂停的 AI 助手 {result.get('skipped', 0)} 人。"
    )


def _query_public_data_tool(args: dict[str, Any]) -> str:
    kind = str(args.get("kind") or args.get("type") or "")
    query = str(args.get("query") or args.get("keyword") or args.get("city") or "")
    params = args.get("params") if isinstance(args.get("params"), dict) else {}
    try:
        from src.platform.public_data_service import query_public_data

        result = query_public_data(kind, query=query, params=params)
    except Exception as exc:
        return f"公共数据查询失败：{exc}"
    return str(result.get("content") or "")


def _subscribe_public_data_tool(args: dict[str, Any]) -> str:
    platform = str(args.get("platform", "") or args.get("_source_provider", "")) or "wecom"
    user_id = str(args.get("user_id") or args.get("from") or args.get("sender_user_id") or "")
    kind = str(args.get("kind") or args.get("type") or "")
    query = str(args.get("query") or args.get("keyword") or args.get("city") or "")
    schedule = str(args.get("schedule") or args.get("time") or "every 1d")
    params = args.get("params") if isinstance(args.get("params"), dict) else {}
    if not user_id:
        return "无法创建订阅：缺少用户身份。"
    try:
        from src.platform.public_data_service import create_subscription

        sub = create_subscription(platform=platform, user_id=user_id, kind=kind, query=query, schedule=schedule, params=params)
    except Exception as exc:
        return f"公共数据订阅创建失败：{exc}"
    return (
        f"已创建公共数据订阅：{sub.get('kind')} {sub.get('query') or ''}，"
        f"检查频率：{sub.get('schedule')}。后续数据变化时会通过 AI 助手通知你。"
    )


def _list_public_data_subscriptions_tool(args: dict[str, Any]) -> str:
    platform = str(args.get("platform", "") or args.get("_source_provider", "")) or ""
    user_id = str(args.get("user_id") or args.get("from") or args.get("sender_user_id") or "")
    try:
        from src.platform.public_data_service import list_subscriptions

        subs = list_subscriptions(user_id=user_id, platform=platform)
    except Exception as exc:
        return f"公共数据订阅查询失败：{exc}"
    if not subs:
        return "你当前没有公共数据订阅。"
    lines = ["你的公共数据订阅："]
    for item in subs[:20]:
        status = "启用" if item.get("enabled") else "停用"
        lines.append(f"- {item.get('kind')} {item.get('query') or ''}：{item.get('schedule')}，{status}")
    return "\n".join(lines)


def _query_ratemin_todos_tool(args: dict[str, Any]) -> str:
    platform = str(args.get("platform", "") or args.get("_source_provider", "")) or "wecom"
    user_id = str(args.get("user_id") or args.get("from") or args.get("sender_user_id") or "")
    query = str(args.get("query") or args.get("keyword") or "")
    source_db = str(args.get("source_db") or args.get("database") or "")
    target_user = str(args.get("target_user") or args.get("name") or args.get("target") or "")
    limit = int(args.get("limit") or 20)
    if not user_id:
        return "无法查询业务系统待办：缺少用户身份。"
    try:
        if target_user:
            from src.platform.ratemin_service import format_ratemin_todos_for_target

            return format_ratemin_todos_for_target(
                platform=platform,
                requester_user_id=user_id,
                target_user=target_user,
                query=query,
                source_db=source_db,
                limit=limit,
            )
        from src.platform.ratemin_service import format_my_ratemin_todos

        return format_my_ratemin_todos(platform=platform, user_id=user_id, query=query, source_db=source_db, limit=limit)
    except Exception as exc:
        return f"业务系统待办查询失败：{exc}"


def _web_research_tool(args: dict[str, Any]) -> str:
    query = str(args.get("query") or args.get("topic") or "")
    max_results = int(args.get("max_results") or 5)
    read_top = int(args.get("read_top") or 3)
    freshness = str(args.get("freshness") or "")
    from src.tools.web_research_service import web_research

    return web_research(query, max_results=max_results, read_top=read_top, freshness=freshness)


def _web_search_aggregate_tool(args: dict[str, Any]) -> str:
    query = str(args.get("query") or args.get("topic") or "")
    max_results = int(args.get("max_results") or 10)
    freshness = str(args.get("freshness") or "")
    domains_raw = args.get("domains")
    domains = domains_raw if isinstance(domains_raw, list) else []
    sources_raw = args.get("include_sources")
    include_sources = sources_raw if isinstance(sources_raw, list) else []
    from src.tools.web_research_service import web_search_aggregate

    return web_search_aggregate(
        query,
        max_results=max_results,
        freshness=freshness,
        domains=[str(item) for item in domains],
        include_sources=[str(item) for item in include_sources],
    )


def _web_research_health_tool(args: dict[str, Any]) -> str:
    from src.tools.web_research_service import web_research_health

    return web_research_health()


def _web_read_tool(args: dict[str, Any]) -> str:
    url = str(args.get("url") or args.get("link") or "")
    max_chars = int(args.get("max_chars") or 6000)
    render = bool(args.get("render") or args.get("dynamic"))
    backend = str(args.get("backend") or args.get("read_backend") or "auto")
    from src.tools.web_research_service import web_read

    return web_read(url, max_chars=max_chars, render=render, backend=backend)


def _web_discover_sources_tool(args: dict[str, Any]) -> str:
    target = str(args.get("url") or args.get("query") or args.get("topic") or "")
    max_items = int(args.get("max_items") or 12)
    from src.tools.web_research_service import discover_public_sources

    return discover_public_sources(target, max_items=max_items)


def _web_random_info_tool(args: dict[str, Any]) -> str:
    topic = str(args.get("topic") or args.get("query") or "")
    count = int(args.get("count") or 3)
    from src.tools.web_research_service import random_public_info

    return random_public_info(topic, count=count)


BUILTIN_TOOLS: list[ToolSpec] = [

    ToolSpec(

        id="builtin:now",

        name="获取当前时间",

        category="system",

        risk_level="none",

        allowed_roles=["personal", "project"],

        description="返回当前的日期和时间",

        parameters={},

        handler=_now_tool,

    ),

    ToolSpec(

        id="builtin:echo",

        name="回声测试",

        category="system",

        risk_level="none",

        allowed_roles=["personal", "project"],

        description="原样返回输入文本",

        parameters={"text": {"type": "string", "description": "要返回的文本"}},

        handler=_echo_tool,

    ),

    ToolSpec(

        id="builtin:create_draft",

        name="创建任务",

        category="task",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="创建新任务。用户说'创建任务'时触发。",

        parameters={

            "title": {"type": "string", "description": "任务标题（必填）"},

            "description": {"type": "string", "description": "任务描述（可选）"},

            "project_id": {"type": "string", "description": "项目空间ID（可选，默认default）"},

            "assignee": {"type": "string", "description": "负责人（可选）"},

        },

        handler=_create_draft_tool,

    ),

    ToolSpec(

        id="builtin:search_knowledge",

        name="搜索知识库（含已索引文档内容）",

        category="knowledge",

        risk_level="none",

        allowed_roles=["personal", "project"],

        description="在知识库中搜索相关资料，包括已上传并索引的 Office/PDF 文档内容。上传的 .docx/.pdf/.xlsx/.pptx 文件会自动提取文本并建立全文索引，此工具可直接搜索到文件中的文字。支持ACL权限过滤。",

        parameters={

            "query": {"type": "string", "description": "搜索关键词"},

            "user_id": {"type": "string", "description": "当前用户ID（可选，提供后按ACL权限过滤结果）"},

        },

        handler=_search_knowledge_tool,

    ),

    ToolSpec(

        id="builtin:approval_followup_workflow",

        name="审批跟踪助手",

        category="workflow",

        risk_level="medium",

        allowed_roles=["personal", "project"],

        description="跨审批、文档和邮件能力，整理审批卡点、补件建议和催办方向。",

        parameters={
            "query": {"type": "string", "description": "审批主题、流程名或问题描述"},
            "user_id": {"type": "string", "description": "当前用户ID"},
        },

        handler=_approval_followup_workflow_tool,

    ),

    ToolSpec(

        id="builtin:meeting_coordination_workflow",

        name="会议组织助手",

        category="workflow",

        risk_level="medium",

        allowed_roles=["personal", "project"],

        description="跨日历、会议和资料能力，生成会议组织建议、议程和后续动作。",

        parameters={
            "query": {"type": "string", "description": "会议主题或会议需求描述"},
            "user_id": {"type": "string", "description": "当前用户ID"},
        },

        handler=_meeting_coordination_workflow_tool,

    ),

    ToolSpec(

        id="builtin:policy_drafting_workflow",

        name="制度起草助手",

        category="workflow",

        risk_level="medium",

        allowed_roles=["personal", "project"],

        description="跨文档、知识和模板参考能力，整理制度、办法、周报、方案的起草建议。",

        parameters={
            "query": {"type": "string", "description": "制度、周报、方案或通知的起草需求"},
            "user_id": {"type": "string", "description": "当前用户ID"},
        },

        handler=_policy_drafting_workflow_tool,

    ),

    ToolSpec(

        id="builtin:workorder_analysis_workflow",

        name="工单分析助手",

        category="workflow",

        risk_level="medium",

        allowed_roles=["personal", "project"],

        description="跨业务系统样板、知识和任务建议能力，分析工单状态与下一步动作。",

        parameters={
            "query": {"type": "string", "description": "工单号或工单异常描述"},
            "user_id": {"type": "string", "description": "当前用户ID"},
        },

        handler=_workorder_analysis_workflow_tool,

    ),

    ToolSpec(

        id="builtin:query_tasks",

        name="查询任务",

        category="task",

        risk_level="none",

        allowed_roles=["personal", "project"],

        description="查询任务列表及状态。用户说'我的任务/任务列表'时触发。",

        parameters={"project_id": {"type": "string", "description": "项目ID（可选）"}},

        handler=_query_tasks_tool,

    ),

    ToolSpec(

        id="builtin:query_attendance",

        name="查询考勤打卡记录（用户说查看打卡/考勤/上周考勤/上月考勤时触发）",

        category="attendance",

        risk_level="low",

        allowed_roles=["personal"],

        description="查询自己的打卡记录。user_id必须用自己的ID。",

        parameters={

            "user_id": {"type": "string", "description": "当前用户的微信ID（必填，从系统提示中的'你的微信ID'获取，不能使用其他人的ID）"},

            "days": {"type": "string", "description": "查询最近几天的记录（可选，默认7天）"},

        },

        handler=_attendance_tool,

    ),

    ToolSpec(

        id="builtin:query_leave",

        name="查询审批/请假/外出记录（用户说查看审批/请假/外出/加班/出差时触发）",

        category="attendance",

        risk_level="low",

        allowed_roles=["personal"],

        description="查询员工自己的审批记录明细（请假、外出、加班、出差等的历史记录）。注意：如果用户问'年假还剩几天'、'假期余额'、'年假剩余'请使用leave_balance工具，不要使用此工具。当用户提到'请假'、'外出'、'加班'、'出差'、'审批记录'、'申请记录'、'我的审批'这些词时使用此工具。user_id参数必须用当前用户自己的ID，从系统提示中的'你的微信ID'获取。",

        parameters={

            "user_id": {"type": "string", "description": "当前用户的微信ID（必填，从系统提示中的'你的微信ID'获取，不能使用其他人的ID）"},

            "days": {"type": "string", "description": "查询最近几天的记录（可选，默认30天）"},

        },

        handler=_leave_tool,

    ),

    ToolSpec(

        id="builtin:leave_balance",

        name="查询年假余额/假期剩余天数/年假还剩几天（用户说年假剩余/假期余额/年假几天/还剩几天假时触发）",

        category="attendance",

        risk_level="low",

        allowed_roles=["personal"],

        description="查询员工自己的年假、事假、病假等各类假期的已休天数和剩余天数。当用户提到'年假剩余'、'年假余额'、'假期余额'、'年假几天'、'还剩几天'、'还剩多少天'、'年假还剩'、'我的假期'、'休假余额'时，必须直接使用此工具。注意：不要使用query_leave工具来查余额，必须用此工具。user_id参数必须用当前用户自己的ID，从系统提示中的'你的微信ID'获取。",

        parameters={

            "user_id": {"type": "string", "description": "当前用户的微信ID（必填，从系统提示中的'你的微信ID'获取）"},

        },

        handler=_leave_balance_tool,

    ),



    ToolSpec(

        id="builtin:query_dept",

        name="查看部门全部数据（负责人查下属考勤+审批）",

        category="attendance",

        risk_level="low",

        allowed_roles=["personal"],

        description="部门负责人查看本部门下属员工的全部数据（考勤打卡和审批记录）。注意：当用户说'部门考勤'或'部门情况'或'团队'或'下属'这些词时，必须直接调用此工具，不要调用其他工具。user_id从系统提示中的'你的微信ID'获取。返回包含考勤和审批两部分数据。",

        parameters={

            "user_id": {"type": "string", "description": "当前用户的微信ID（必填）"},

        },

        handler=_dept_attendance_tool,

    ),

    ToolSpec(

        id="builtin:query_subordinate",

        name="查询下属员工数据（负责人通过姓名查下属时触发）",

        category="attendance",

        risk_level="low",

        allowed_roles=["personal"],

        description="部门负责人通过姓名查询特定下属员工的考勤或审批记录。当负责人说'张三的考勤'或'李四的请假'或'张三上周的考勤'或'李四的审批'等时，使用此工具。name参数填员工姓名，type参数填'attendance'考勤或'approval'审批。",

        parameters={

            "user_id": {"type": "string", "description": "当前用户的微信ID（必填）"},

            "name": {"type": "string", "description": "员工姓名（必填，如'张三'、'李四'）"},

            "type": {"type": "string", "description": "查询类型：'attendance'考勤或'approval'审批"},

            "days": {"type": "string", "description": "查询最近几天（默认7天）"},

        },

        handler=_subordinate_tool,

    ),

    ToolSpec(

        id="builtin:query_subordinate_balance",

        name="查询下属假期余额（负责人查下属年假/事假剩余天数时触发）",

        category="attendance",

        risk_level="low",

        allowed_roles=["personal"],

        description="部门负责人查询特定下属员工的年假、事假等各类假期余额。当负责人说'查某人的假期余额'或'某人还剩几天假'或'某人的年假'或'下属的假期'时，使用此工具。name参数填员工姓名。注意：这个工具只能由部门负责人使用，查询的是下属的假期数据。",

        parameters={

            "user_id": {"type": "string", "description": "当前用户的微信ID（必填）"},

            "name": {"type": "string", "description": "下属员工姓名（必填，如'张三'、'李四'）"},

        },

        handler=_subordinate_balance_tool,

    ),

    ToolSpec(

        id="builtin:weather",

        name="天气查询（实时气温、风力、湿度、未来3天预报）",

        category="search",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="查询任意城市的实时天气和未来3天天气预报。当用户提到'天气'、'气温'、'温度'、'会不会下雨'、'刮风'、'天气预报'、'今天多少度'、'冷吗'、'热吗'时，必须使用此工具。返回温度、体感温度、湿度、风力、天气状况和3天预报。",

        parameters={

            "city": {"type": "string", "description": "城市名称（必填），如'北京'、'上海'、'烟台'、'London'"},

        },

        handler=lambda a: __import__('importlib').import_module('src.tools.weather').weather_forecast(a.get('city', '')),

    ),

    ToolSpec(

        id="builtin:anysearch",

        name="搜索互联网（新闻、百科、美食、公交、资讯、查询信息）",

        category="search",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="通过搜索引擎搜索互联网获取各类实时信息。当用户问'查一下'、'搜索'、'找资料'、'查询信息'、'找美食'、'找公交'、'查路线'、'找景点'、'百科'、'新闻'、'资讯'、'攻略'、'推荐'时，必须使用此工具。这是主要的搜索工具。参数query填搜索关键词。",

        parameters={

            "query": {"type": "string", "description": "搜索关键词（必填），如'烟台公交路线'、'烟台美食推荐'"},

        },

        handler=lambda a: __import__('importlib').import_module('src.tools.anysearch_client').anysearch(a.get('query', '')),

    ),

    ToolSpec(

        id="builtin:generate_document",

        name="生成文档（周报/纪要/报告/甘特图→DOCX/XLSX/PPTX）",

        category="document",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="生成docx/xlsx/pptx文档推送给用户。当用户说'生成文档/报告/周报/纪要/合同/通知'或要求把内容做成文件时使用。",

        parameters={

            "title": {"type": "string", "description": "文档标题（必填）"},

            "content": {"type": "string", "description": "文档内容，段落间空一行"},

            "format": {"type": "string", "description": "docx/xlsx/pptx（默认docx）"},

            "from": {"type": "string", "description": "用户ID"},

        },

        handler=_generate_report_handler,
    ),
    ToolSpec(

        id="builtin:cron_list",

        name="查看定时任务列表",

        category="system",

        risk_level="none",

        allowed_roles=["personal", "project"],

        description="查看当前已注册的定时任务。当用户说'定时任务'、'计划任务'、'定时器'时使用。",

        parameters={},

        handler=lambda a: __import__('importlib').import_module('src.orchestrator.cron_job').list_jobs(),

    ),

    ToolSpec(

        id="builtin:tushare",

        name="查股票行情、股价、K线、金融数据",

        category="finance",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="通过Tushare专业版查询A股/港股/美股行情、K线数据、股票列表。当用户提到'股票'、'行情'、'K线'、'股价'、'指数'、'平安银行'、'茅台'、'上证'、'深证'等股市相关词时，必须使用此工具。常用code: 000001.SZ(平安银行), 600519.SH(茅台), 000001.SH(上证指数)。常用method: daily(日K线), monthly(月K线), stock_basic(股票列表)。其他参数自动传递给API。",

        parameters={

            "method": {"type": "string", "description": "API方法名：daily(日K线)、monthly(月K线)、stock_basic(股票列表)"},

            "code": {"type": "string", "description": "股票代码：(必填)如000001.SZ平安银行、600519.SH贵州茅台、000001.SH上证指数"},

        },

        handler=_tushare_tool,

    ),

    ToolSpec(

        id="builtin:transition_task",

        name="更新任务状态（进行中/完成/阻塞/取消）",

        category="task",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="更新指定任务的状态。当用户说'完成任务'、'开始任务'、'把任务标记为'、'阻塞'、'移入'时使用。status有效值：in_progress(进行中)、done(完成)、blocked(阻塞)、cancelled(取消)。",

        parameters={

            "task_id": {"type": "string", "description": "任务ID（必填）"},

            "status": {"type": "string", "description": "目标状态：in_progress/done/blocked/cancelled"},

            "blocked_reason": {"type": "string", "description": "阻塞原因（仅blocked状态时需要）"},

        },

        handler=_transition_task_tool,

    ),

    ToolSpec(

        id="builtin:search_tasks",

        name="搜索任务",

        category="task",

        risk_level="none",

        allowed_roles=["personal", "project"],

        description="按关键词搜索任务。当用户说'搜索任务'、'查找任务'、'找任务'时使用。",

        parameters={

            "keyword": {"type": "string", "description": "搜索关键词（必填）"},

            "project_id": {"type": "string", "description": "项目ID（可选）"},

            "limit": {"type": "string", "description": "返回条数上限（可选，默认20）"},

        },

        handler=_search_tasks_tool,

    ),

    ToolSpec(

        id="builtin:task_analytics",

        name="查看任务统计",

        category="task",

        risk_level="none",

        allowed_roles=["personal", "project"],

        description="查看任务完成率、逾期数、依赖链等统计。当用户说'任务统计'、'完成率'、'项目进度'、'统计'时使用。",

        parameters={

            "project_id": {"type": "string", "description": "项目ID（可选，不传则返回全局统计）"},

        },

        handler=_task_analytics_tool,

    ),

    ToolSpec(

        id="builtin:work_journal",

        name="查看工作日志",

        category="task",

        risk_level="none",

        allowed_roles=["personal", "project"],

        description="查看指定用户的工作日志（任务汇总）。当用户说'工作日志'、'我的工作'、'工作记录'时使用。",

        parameters={

            "user_id": {"type": "string", "description": "用户ID（必填）"},

        },

        handler=_work_journal_tool,

    ),

    ToolSpec(

        id="builtin:list_spaces",

        name="查看项目空间",

        category="task",

        risk_level="none",

        allowed_roles=["personal", "project"],

        description="查看所有项目空间及统计。当用户说'项目空间'、'查看空间'、'空间列表'时使用。",

        parameters={},

        handler=_list_spaces_tool,

    ),

    ToolSpec(

        id="builtin:list_knowledge",

        name="查看知识库列表",

        category="knowledge",

        risk_level="none",

        allowed_roles=["personal", "project"],

        description="列出知识库中的条目。当用户提供user_id时按ACL权限过滤；否则用owner_type/owner_id直接查询。",

        parameters={

            "owner_type": {"type": "string", "description": "所有者类型：organization/project/user（可选）"},

            "owner_id": {"type": "string", "description": "所有者ID（可选，需配合owner_type使用）"},

            "user_id": {"type": "string", "description": "当前用户ID（可选，提供后按ACL权限过滤）"},

        },

        handler=_list_knowledge_tool,

    ),

    ToolSpec(

        id="builtin:promote_knowledge",

        name="升级知识条目作用域",

        category="knowledge",

        risk_level="medium",

        allowed_roles=["personal", "project"],

        description="将知识条目从个人/项目作用域升级到部门或企业公共作用域，用于沉淀可复用经验。",

        parameters={

            "entry_id": {"type": "string", "description": "知识条目ID（必填）"},
            "target_scope": {"type": "string", "description": "目标作用域：personal/project/department/organization"},
            "target_id": {"type": "string", "description": "目标作用域ID（必填）"},

        },

        handler=_promote_knowledge_tool,

    ),

    ToolSpec(

        id="builtin:update_knowledge",

        name="更新知识条目",

        category="knowledge",

        risk_level="medium",

        allowed_roles=["personal", "project"],

        description="更新知识库中的既有条目内容、标题或标签。当用户说'更新知识库'、'修改知识条目'、'改一下这条知识'时使用。",

        parameters={

            "entry_id": {"type": "string", "description": "知识条目ID（必填）"},
            "content": {"type": "string", "description": "新的正文内容（必填）"},
            "title": {"type": "string", "description": "新的标题（可选）"},
            "tags": {"type": "string", "description": "新的标签列表，逗号分隔（可选）"},

        },

        handler=_update_knowledge_tool,

    ),

    ToolSpec(

        id="builtin:delete_knowledge",

        name="删除知识条目",

        category="knowledge",

        risk_level="high",

        allowed_roles=["personal", "project"],

        description="删除知识库中的指定条目。当用户说'删除这条知识'、'移除知识条目'、'清理知识库'时使用。",

        parameters={

            "entry_id": {"type": "string", "description": "知识条目ID（必填）"},
            "user_id": {"type": "string", "description": "当前用户ID（可选，用于权限校验）"},

        },

        handler=_delete_knowledge_tool,

    ),

    ToolSpec(

        id="builtin:import_company_guides",

        name="导入公司级说明书到知识库",

        category="knowledge",

        risk_level="medium",

        allowed_roles=["personal", "project"],

        description="将系统内置的四份公司级操作说明书作为普通公司文档导入公司知识库，带稳定标题和关键词。",

        parameters={},

        handler=_import_company_guides_tool,

    ),

    ToolSpec(

        id="builtin:write_scoped_memory",

        name="写入作用域记忆",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="向个人/部门/项目/群组作用域写入一条结构化记忆，用于后续协作检索。",

        parameters={

            "scope_type": {"type": "string", "description": "作用域：personal/department/project/group"},
            "scope_id": {"type": "string", "description": "作用域ID（必填）"},
            "content": {"type": "string", "description": "记忆内容（必填）"},
            "source": {"type": "string", "description": "来源标记（可选）"},

        },

        handler=_write_scoped_memory_tool,

    ),

    ToolSpec(

        id="builtin:promote_scoped_memory",

        name="升级作用域记忆",

        category="productivity",

        risk_level="medium",

        allowed_roles=["personal", "project"],

        description="将作用域记忆从个人提升到项目/部门等更高层作用域，支持经验沉淀。",

        parameters={

            "source_scope_type": {"type": "string", "description": "源作用域：personal/department/project/group"},
            "source_scope_id": {"type": "string", "description": "源作用域ID（必填）"},
            "target_scope_type": {"type": "string", "description": "目标作用域：personal/department/project/group"},
            "target_scope_id": {"type": "string", "description": "目标作用域ID（必填）"},
            "query": {"type": "string", "description": "用于选择要升级记忆的关键词（必填）"},

        },

        handler=_promote_scoped_memory_tool,

    ),

    ToolSpec(

        id="builtin:add_document",

        name="添加文档到知识库（声明归属）",

        category="knowledge",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="将文档添加至知识库并声明归属范围。scope可选：personal(个人)/project(项目)/department(部门)/company(公司)。需对应权限。",

        parameters={

            "title": {"type": "string", "description": "文档标题（必填）"},

            "content": {"type": "string", "description": "文档内容（必填）"},

            "scope": {"type": "string", "description": "归属范围：personal/project/department/company（可选，默认personal）"},

            "user_id": {"type": "string", "description": "当前用户ID（必填）"},

            "owner_id": {"type": "string", "description": "归属对象ID（可选，personal默认user_id，其他默认*）"},

        },

        handler=_add_document_tool,

    ),

    ToolSpec(

        id="builtin:set_priority",

        name="设置任务优先级",

        category="task",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="设置任务的优先级。当用户说'设为高优先级'、'设置优先级'、'优先级改为'时使用。",

        parameters={

            "task_id": {"type": "string", "description": "任务ID（必填）"},

            "priority": {"type": "string", "description": "优先级：high/medium/low（必填）"},

        },

        handler=_set_priority_tool,

    ),

    ToolSpec(

        id="builtin:send_email",

        name="发送邮件",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="通过SMTP发送电子邮件。当用户说'发送邮件'、'发邮件'、'写邮件'、'给某人发邮件'时使用。",

        parameters={

            "to": {"type": "string", "description": "收件人邮箱（必填）"},

            "subject": {"type": "string", "description": "邮件主题（必填）"},

            "body": {"type": "string", "description": "邮件正文（必填）"},

            "cc": {"type": "string", "description": "抄送邮箱（可选）"},

        },

        handler=_send_email_tool,

    ),

    ToolSpec(

        id="builtin:list_emails",

        name="查看收件箱",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="查看收件箱最新邮件。当用户说'查看邮件'、'收件箱'、'邮件列表'、'新邮件'时使用。",

        parameters={

            "limit": {"type": "string", "description": "返回条数（可选，默认10）"},

        },

        handler=_list_emails_tool,

    ),

    ToolSpec(

        id="builtin:search_emails",

        name="搜索邮件",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="在收件箱中搜索邮件。当用户说'搜索邮件'、'找邮件'、'查找邮件'时使用。",

        parameters={

            "query": {"type": "string", "description": "搜索关键词（必填），如'项目报告'、'张三'"},

        },

        handler=_search_emails_tool,

    ),

    ToolSpec(

        id="builtin:get_email",

        name="查看邮件详情",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="查看指定邮件的完整内容。当用户说'查看邮件内容'、'打开邮件'、'邮件详情'时使用。uid参数来自list_emails或search_emails的结果。",

        parameters={

            "uid": {"type": "string", "description": "邮件UID（必填，来自list_emails的结果）"},

        },

        handler=_get_email_tool,

    ),

    ToolSpec(

        id="builtin:merge_pdfs",

        name="合并PDF文件",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="合并多个PDF文件为一个。当用户说'合并PDF'、'合并文件'、'PDF合并'时使用。paths参数用逗号分隔多个文件路径。",

        parameters={

            "paths": {"type": "string", "description": "PDF文件路径列表，用逗号分隔（必填）"},

            "output": {"type": "string", "description": "输出文件名（可选，默认merged.pdf）"},

        },

        handler=_merge_pdfs_tool,

    ),

    ToolSpec(

        id="builtin:split_pdf",

        name="拆分PDF文件",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="拆分PDF文件的指定页面。当用户说'拆分PDF'、'提取页面'、'PDF拆页'时使用。pages参数格式如'1-3,5,7-9'。",

        parameters={

            "path": {"type": "string", "description": "PDF文件路径（必填）"},

            "pages": {"type": "string", "description": "页面范围，如'1-3,5,7-9'（必填）"},

            "output": {"type": "string", "description": "输出文件名（可选，默认split.pdf）"},

        },

        handler=_split_pdf_tool,

    ),

    ToolSpec(

        id="builtin:compress_pdf",

        name="压缩PDF文件",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="压缩PDF文件减小体积。当用户说'压缩PDF'、'PDF压缩'、'减小PDF大小'时使用。",

        parameters={

            "path": {"type": "string", "description": "PDF文件路径（必填）"},

            "output": {"type": "string", "description": "输出文件名（可选，默认compressed.pdf）"},

        },

        handler=_compress_pdf_tool,

    ),

    ToolSpec(

        id="builtin:protect_pdf",

        name="加密PDF文件",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="为PDF文件设置密码保护。当用户说'加密PDF'、'PDF加密码'、'保护PDF'时使用。",

        parameters={

            "path": {"type": "string", "description": "PDF文件路径（必填）"},

            "password": {"type": "string", "description": "访问密码（必填）"},

            "output": {"type": "string", "description": "输出文件名（可选，默认protected.pdf）"},

        },

        handler=_protect_pdf_tool,

    ),

    ToolSpec(

        id="builtin:read_pdf",

        name="读取PDF文本",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="提取 PDF 文本内容。当用户说'读取PDF'、'查看PDF内容'、'提取PDF文字'时使用。",

        parameters={

            "path": {"type": "string", "description": "PDF文件路径（必填）"},

        },

        handler=_read_pdf_tool,

    ),

    ToolSpec(

        id="builtin:extract_pdf_images",

        name="提取PDF图片",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="提取 PDF 中的图片资源。当用户说'提取PDF图片'、'导出PDF图片'时使用。",

        parameters={

            "path": {"type": "string", "description": "PDF文件路径（必填）"},

            "output_dir": {"type": "string", "description": "输出目录（可选，默认pdf_images）"},

        },

        handler=_extract_pdf_images_tool,

    ),

    ToolSpec(

        id="builtin:watermark_pdf",

        name="添加PDF水印",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="为 PDF 添加文字水印。当用户说'给PDF加水印'、'PDF水印'时使用。",

        parameters={

            "path": {"type": "string", "description": "PDF文件路径（必填）"},

            "watermark": {"type": "string", "description": "水印文字（必填）"},

            "output": {"type": "string", "description": "输出文件名（可选，默认watermarked.pdf）"},

        },

        handler=_watermark_pdf_tool,

    ),

    ToolSpec(

        id="builtin:pdf_service_status",

        name="查看PDF服务状态",

        category="system",

        risk_level="none",

        allowed_roles=["personal", "project"],

        description="查看当前本地 PDF 处理后端的可用状态，用于排查 PDF 能力是否已就绪。",

        parameters={},

        handler=_pdf_service_status_tool,

    ),

    ToolSpec(

        id="builtin:office_service_status",

        name="查看Office服务状态",

        category="system",

        risk_level="none",

        allowed_roles=["personal", "project"],

        description="查看当前本地 Office 文档处理后端的可用状态，用于排查 docx/xlsx/pptx 能力是否已就绪。",

        parameters={},

        handler=_office_service_status_tool,

    ),

    ToolSpec(

        id="builtin:docx_template_outline",

        name="提取DOCX模板结构",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="提取 DOCX 模板结构摘要，用于模板调试、排查和后续结构化填充。",

        parameters={

            "path": {"type": "string", "description": "DOCX模板路径（必填）"},

        },

        handler=_docx_template_outline_tool,

    ),

    ToolSpec(

        id="builtin:xlsx_template_outline",

        name="提取XLSX模板结构",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="提取 XLSX 模板结构摘要，用于表格模板调试、排查和后续结构化填充。",

        parameters={

            "path": {"type": "string", "description": "XLSX模板路径（必填）"},

        },

        handler=_xlsx_template_outline_tool,

    ),

    ToolSpec(

        id="builtin:pptx_template_outline",

        name="提取PPTX模板结构",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="提取 PPTX 模板结构摘要，用于演示文稿模板调试、排查和后续结构化填充。",

        parameters={

            "path": {"type": "string", "description": "PPTX模板路径（必填）"},

        },

        handler=_pptx_template_outline_tool,

    ),

    ToolSpec(

        id="builtin:read_docx",

        name="读取DOCX文本",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="读取 DOCX 文本内容。当用户说'读取docx'、'查看word内容'时使用。",

        parameters={

            "path": {"type": "string", "description": "DOCX文件路径（必填）"},

        },

        handler=_read_docx_tool,

    ),

    ToolSpec(

        id="builtin:read_xlsx",

        name="读取XLSX内容",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="读取 XLSX 表格内容。当用户说'读取xlsx'、'查看表格内容'时使用。",

        parameters={

            "path": {"type": "string", "description": "XLSX文件路径（必填）"},

        },

        handler=_read_xlsx_tool,

    ),

    ToolSpec(

        id="builtin:read_pptx",

        name="读取PPTX内容",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="读取 PPTX 幻灯片文本内容。当用户说'读取pptx'、'查看PPT内容'时使用。",

        parameters={

            "path": {"type": "string", "description": "PPTX文件路径（必填）"},

        },

        handler=_read_pptx_tool,

    ),

    ToolSpec(

        id="builtin:ocr_pdf",

        name="OCR识别PDF",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="对扫描型 PDF 执行 OCR 识别并生成可搜索 PDF。当用户说'OCR PDF'、'识别扫描PDF'时使用。",

        parameters={

            "path": {"type": "string", "description": "输入PDF路径（必填）"},

            "output": {"type": "string", "description": "输出文件名（可选，默认ocr.pdf）"},

            "language": {"type": "string", "description": "OCR语言（可选，默认chi_sim+eng）"},

        },

        handler=_ocr_pdf_tool,

    ),

    ToolSpec(

        id="builtin:ddg_search",

        name="DuckDuckGo搜索（备选搜索引擎）",

        category="search",

        risk_level="none",

        allowed_roles=["personal", "project"],

        description="通过DuckDuckGo搜索互联网。当anysearch不可用时作为备选搜索工具。搜索新闻、百科、资讯等实时信息。",

        parameters={

            "query": {"type": "string", "description": "搜索关键词（必填）"},

        },

        handler=_ddg_search_tool,

    ),

    ToolSpec(

        id="builtin:contact_search",

        name="查找联系人（跨平台通讯录搜索）",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="搜索企业通讯录中的联系人。支持飞书和钉钉。当用户说'找人'、'查联系人'、'搜索同事'、'找某某'时使用。",

        parameters={

            "query": {"type": "string", "description": "搜索关键词，姓名或手机号（必填）"},

        },

        handler=_contact_search_tool,

    ),

    ToolSpec(

        id="builtin:calendar_agenda",

        name="查看日程/会议安排",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="查看近期日程和会议安排。支持飞书和钉钉。当用户说'查看日程'、'今天会议'、'本周安排'、'日历'时使用。",

        parameters={

            "days": {"type": "string", "description": "查询未来几天（可选，默认7）"},

        },

        handler=_calendar_agenda_tool,

    ),

    ToolSpec(

        id="builtin:doc_search",

        name="搜索企业文档",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="搜索企业知识库和文档。支持飞书文档和钉钉文档。当用户说'搜索文档'、'找文件'、'查资料'时使用。",

        parameters={

            "query": {"type": "string", "description": "搜索关键词（必填）"},

        },

        handler=_doc_search_tool,

    ),

    ToolSpec(

        id="builtin:read_docs",

        name="读取企业文档内容",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="读取企业文档或在线文档的正文摘要。当用户说'打开文档'、'读取文档内容'、'看看这份文档写了什么'时使用。",

        parameters={

            "query": {"type": "string", "description": "文档标题或关键词（必填）"},

        },

        handler=_read_docs_tool,

    ),

    ToolSpec(

        id="builtin:drive_search",

        name="搜索企业网盘",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="搜索企业网盘或云盘中的文件。当用户说'搜索网盘'、'找网盘文件'、'查共享盘资料'时使用。",

        parameters={

            "query": {"type": "string", "description": "网盘搜索关键词（必填）"},

        },

        handler=_drive_search_tool,

    ),

    ToolSpec(

        id="builtin:read_drive",

        name="读取网盘文件内容",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="读取已同步到系统的网盘文件正文摘要。当用户说'打开网盘文件'、'读取共享盘内容'时使用。",

        parameters={

            "query": {"type": "string", "description": "网盘文件名称或关键词（必填）"},

        },

        handler=_read_drive_tool,

    ),

    ToolSpec(

        id="builtin:mail_summary",

        name="汇总企业邮箱",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="汇总企业邮箱中的邮件信息。当用户说'汇总邮件'、'看看今天的邮件'、'总结邮箱消息'时使用。",

        parameters={

            "query": {"type": "string", "description": "邮箱筛选关键词（可选）"},

        },

        handler=_mail_summary_tool,

    ),

    ToolSpec(

        id="builtin:list_capabilities",

        name="查看当前可用能力协议",

        category="system",

        risk_level="none",

        allowed_roles=["personal", "project"],

        description="查看当前 Bot 后端已接入的能力协议、对应方法和提供者，用于调试、交接或能力盘点。",

        parameters={},

        handler=_list_capabilities_tool,

    ),

    ToolSpec(

        id="builtin:approval_list",

        name="查看审批待办",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="查看待审批/已审批的审批单。支持飞书审批和钉钉审批。当用户说'审批'、'待审批'、'我的审批'时使用。",

        parameters={

            "status": {"type": "string", "description": "审批状态：pending待审批/done已审批（可选，默认pending）"},

        },

        handler=_approval_list_tool,

    ),

    ToolSpec(

        id="builtin:approval_detail",

        name="查看审批详情",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="查看审批单详情或更细的审批信息。当用户说'审批详情'、'打开审批单'时使用。",

        parameters={

            "query": {"type": "string", "description": "审批单关键词或状态（可选）"},

        },

        handler=_approval_detail_tool,

    ),

    ToolSpec(

        id="builtin:enterprise_app_query",

        name="查询企业应用和流程数据",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="查询企业 IM 内置应用、审批流程、会议室、日程、在线文档、第三方应用或内部业务系统数据。用户问会议室是否被申请、审批流程进度、多个应用数据汇总时优先使用。",

        parameters={

            "query": {"type": "string", "description": "用户要查询的企业应用、流程、会议室、审批或第三方系统问题"},

        },

        handler=_enterprise_app_query_tool,

    ),

    ToolSpec(

        id="builtin:enterprise_app_action",

        name="执行企业应用动作",

        category="productivity",

        risk_level="medium",

        allowed_roles=["personal", "project"],

        description="根据用户明确指令调用企业应用或流程执行动作，例如创建会议、创建日程或后续接入的审批催办。执行前应确认动作、对象和时间等关键参数。",

        parameters={

            "action": {"type": "string", "description": "动作 ID，例如 meeting.create 或 calendar.create"},

            "title": {"type": "string", "description": "会议或流程标题，可选"},

            "summary": {"type": "string", "description": "日程标题，可选"},

            "start_at": {"type": "string", "description": "开始时间，可选"},

            "end_at": {"type": "string", "description": "结束时间，可选"},

            "attendees": {"type": "string", "description": "参与人 UserID，逗号分隔，可选"},

        },

        handler=_enterprise_app_action_tool,

    ),

    ToolSpec(

        id="builtin:calendar_create",

        name="创建日程/会议",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="创建日程或会议邀请。支持飞书和钉钉。当用户说'创建日程'、'安排会议'、'预约'时使用。",

        parameters={

            "summary": {"type": "string", "description": "日程标题（必填）"},

            "start": {"type": "string", "description": "开始时间，格式 YYYY-MM-DD HH:MM（必填）"},

            "end": {"type": "string", "description": "结束时间，格式 YYYY-MM-DD HH:MM（必填）"},

        },

        handler=_calendar_create_tool,

    ),

    ToolSpec(

        id="builtin:create_doc",

        name="创建企业文档",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="在企业微信中创建文档。当用户说'创建文档'、'写文档'、'新建文档'时使用。",

        parameters={

            "title": {"type": "string", "description": "文档标题（必填）"},

            "content": {"type": "string", "description": "文档内容（可选）"},

        },

        handler=_create_doc_tool,

    ),

    ToolSpec(

        id="builtin:smartpage_create",

        name="创建企业微信智能文档",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="在企业微信中创建智能文档，支持 Markdown 内容和多页面内容整理。当用户要求生成在线智能文档、汇总成企微智能文档时使用。",

        parameters={

            "title": {"type": "string", "description": "智能文档标题（必填）"},

            "content": {"type": "string", "description": "文档正文，支持 Markdown（可选）"},

        },

        handler=_smartpage_create_tool,

    ),

    ToolSpec(

        id="builtin:edit_doc_content",

        name="编辑企业微信文档内容",

        category="productivity",

        risk_level="medium",

        allowed_roles=["personal", "project"],

        description="向已有企业微信文档写入或追加内容。只有用户明确要求编辑已有在线文档时使用。",

        parameters={

            "doc_id": {"type": "string", "description": "文档 ID 或文档标识（必填）"},

            "content": {"type": "string", "description": "要写入的内容，支持 Markdown（必填）"},

        },

        handler=_edit_doc_content_tool,

    ),

    ToolSpec(

        id="builtin:sheet_append",

        name="追加企业微信表格数据",

        category="productivity",

        risk_level="medium",

        allowed_roles=["personal", "project"],

        description="向企业微信表格追加一行或多行数据。当用户要求把结果写入企微表格、追加表格记录时使用。",

        parameters={

            "doc_id": {"type": "string", "description": "表格文档 ID（必填）"},

            "values": {"type": "string", "description": "要追加的数据，可为 JSON 数组或逗号分隔文本（必填）"},

        },

        handler=_sheet_append_tool,

    ),

    ToolSpec(

        id="builtin:todo_create",

        name="创建企业微信待办",

        category="productivity",

        risk_level="medium",

        allowed_roles=["personal", "project"],

        description="创建企业微信待办，可指定主题、截止时间和参与人。当用户说创建待办、提醒某人处理、安排任务时使用。",

        parameters={

            "title": {"type": "string", "description": "待办主题或内容（必填）"},

            "due_time": {"type": "string", "description": "截止时间，例如 明天下午3点 或 2026-07-14 15:00（可选）"},

            "participants": {"type": "string", "description": "参与人 userid，多个用逗号分隔（可选）"},

        },

        handler=_todo_create_tool,

    ),

    ToolSpec(

        id="builtin:todo_list",

        name="查询企业微信待办",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="查询当前授权用户的企业微信待办列表。当用户问我的待办、本周待办、待办状态时使用。",

        parameters={

            "query": {"type": "string", "description": "待办筛选关键词或时间范围（可选）"},

        },

        handler=_todo_list_tool,

    ),

    ToolSpec(

        id="builtin:todo_update",

        name="更新企业微信待办",

        category="productivity",

        risk_level="medium",

        allowed_roles=["personal", "project"],

        description="更新机器人创建的企业微信待办标题、截止时间或状态。只有用户明确要求修改待办时使用。",

        parameters={

            "todo_id": {"type": "string", "description": "待办 ID（必填）"},

            "title": {"type": "string", "description": "新的待办标题或内容（可选）"},

            "status": {"type": "string", "description": "状态，例如 accepted、done、rejected 或已完成（可选）"},

            "due_time": {"type": "string", "description": "新的截止时间（可选）"},

        },

        handler=_todo_update_tool,

    ),

    ToolSpec(

        id="builtin:todo_user_search",

        name="搜索企业微信待办参与人",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="根据姓名或别名搜索可加入待办的成员 userid。当创建待办前需要查找张三、李四等成员时使用。",

        parameters={

            "query": {"type": "string", "description": "成员姓名或别名（必填）"},

        },

        handler=_todo_user_search_tool,

    ),

    ToolSpec(

        id="builtin:list_meetings",

        name="查看会议列表",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="查看近期的会议安排。支持企业微信和钉钉。当用户说'查看会议'、'我的会议'、'会议列表'时使用。",

        parameters={},

        handler=_list_meetings_tool,

    ),

    ToolSpec(

        id="builtin:meeting_detail",

        name="查看会议详情",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="查看会议详情。当用户说'会议详情'、'打开这个会议'时使用。",

        parameters={

            "query": {"type": "string", "description": "会议标题或关键词（可选）"},

        },

        handler=_meeting_detail_tool,

    ),

    ToolSpec(

        id="builtin:create_meeting",

        name="创建会议",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="创建预约会议。支持企业微信。当用户说'创建会议'、'预约会议'、'安排会议'时使用。",

        parameters={

            "title": {"type": "string", "description": "会议标题（必填）"},

            "start": {"type": "string", "description": "开始时间，格式 YYYY-MM-DD HH:MM（必填）"},

            "end": {"type": "string", "description": "结束时间，格式 YYYY-MM-DD HH:MM（必填）"},

            "attendees": {"type": "string", "description": "参会者UserID，逗号分隔（可选）"},

        },

        handler=_create_meeting_tool,

    ),

    ToolSpec(

        id="builtin:calendar_detail",

        name="查看日程详情",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="查看日程详情或更大范围的日程信息。当用户说'日程详情'、'打开这个日程'时使用。",

        parameters={

            "query": {"type": "string", "description": "日程关键词（可选）"},

        },

        handler=_calendar_detail_tool,

    ),

    ToolSpec(

        id="builtin:who_is_admin",

        name="查看平台管理员列表",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="列出已配置平台上（飞书/钉钉/企微）的企业管理员。当用户说'平台管理员'、'企业管理员'、'谁是管理员'时使用。注意：查询部门负责人请用who_is_leader工具，两者不同。",

        parameters={},

        handler=_who_is_admin_tool,

    ),

    ToolSpec(

        id="builtin:who_is_leader",

        name="查看部门负责人列表",

        category="productivity",

        risk_level="none",

        allowed_roles=["personal", "project"],

        description="列出企业微信中的部门负责人。当用户说'部门负责人'、'谁是部门负责人'、'部门领导'时使用。注意：这是部门负责人，与企业管理员不同。",

        parameters={},

        handler=_who_is_leader_tool,

    ),

    ToolSpec(

        id="builtin:register_cloud_drive",

        name="注册云盘（管理员/负责人配置）",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="注册云盘同步配置。支持12+云盘：onedrive/googledrive/aliyundrive/baidu/dropbox/mega等。公司级需leader、项目级需admin。用户说'添加云盘'、'配置云盘'、'注册云盘'时使用。",

        parameters={

            "name": {"type": "string", "description": "云盘名称（必填）"},

            "driver_type": {"type": "string", "description": "云盘类型：onedrive/googledrive/aliyundrive/baidu/dropbox/mega/jianguo/nextcloud/icloud/tianyi/p115/quark"},

            "scope": {"type": "string", "description": "归属范围：organization(公司)/department(部门)/project(项目)"},

            "scope_id": {"type": "string", "description": "范围ID（部门ID或项目ID，*表示全部）"},

            "rclone_remote": {"type": "string", "description": "rclone remote名称（可选）"},

            "user_id": {"type": "string", "description": "操作人ID"},

        },

        handler=_register_cloud_drive_tool,

    ),

    ToolSpec(

        id="builtin:list_cloud_drives",

        name="查看已配置云盘",

        category="productivity",

        risk_level="none",

        allowed_roles=["personal", "project"],

        description="列出已注册的云盘及最近同步状态。用户说'查看云盘'、'云盘列表'、'已配置云盘'时使用。",

        parameters={

            "scope": {"type": "string", "description": "筛选范围（可选）"},

            "user_id": {"type": "string", "description": "用户ID"},

        },

        handler=_list_cloud_drives_tool,

    ),

    ToolSpec(

        id="builtin:sync_from_cloud",

        name="从云盘同步到知识库",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="从已注册的云盘同步文件到本地并自动索引到知识库。用户说'同步云盘'、'同步文件'、'从云盘下载'时使用。",

        parameters={

            "drive_id": {"type": "string", "description": "云盘ID（必填，来自list_cloud_drives）"},

            "remote_path": {"type": "string", "description": "云盘路径（必填）"},

            "local_path": {"type": "string", "description": "本地路径（可选）"},

            "user_id": {"type": "string", "description": "用户ID"},

        },

        handler=_sync_from_cloud_tool,

    ),

    ToolSpec(

        id="builtin:delete_cloud_drive",

        name="删除云盘配置",

        category="productivity",

        risk_level="high",

        allowed_roles=["personal", "project"],

        description="删除已注册的云盘配置。仅管理员可操作。用户说'删除云盘'、'移除云盘'时使用。",

        parameters={

            "drive_id": {"type": "string", "description": "云盘ID（必填）"},

            "user_id": {"type": "string", "description": "用户ID"},

        },

        handler=_delete_cloud_drive_tool,

    ),

    # Role tools

    ToolSpec(

        id="builtin:select_role",

        name="AI角色选择（自动匹配专家）",

        category="system",

        risk_level="none",

        allowed_roles=["personal", "project"],

        description="【自动调用】根据用户请求内容自动选择最适合的AI专家角色（支持215个角色）。工具返回角色名，然后用自然语言告知用户后继续工作。用户说'换一个角色'、'换个专家'、'这个不对'时重新选择。",

        parameters={

            "query": {"type": "string", "description": "用户需求描述（必填）"},

        },

        handler=_select_role_tool,

    ),

    ToolSpec(

        id="builtin:list_roles",

        name="列出AI角色列表",

        category="system",

        risk_level="none",

        allowed_roles=["personal", "project"],

        description="列出所有可用的 AI 专家角色，可按领域筛选。用户说'有哪些角色'、'可用角色'、'专家列表'时使用。",

        parameters={

            "category": {"type": "string", "description": "筛选领域（可选）：engineering/design/marketing/finance/hr/legal/sales/supply-chain/testing/product/specialized"},

        },

        handler=_list_roles_tool,

    ),

    ToolSpec(

        id="builtin:set_role",

        name="切换AI角色",

        category="system",

        risk_level="none",

        allowed_roles=["personal", "project"],

        description="手动切换到指定 AI 专家角色。当用户说'换个角色'、'切换到'、'用XX角色'时使用。参数name填角色中文名称如'小红书运营专家'。",

        parameters={

            "name": {"type": "string", "description": "角色名称，如'前端开发者'、'安全工程师'、'小红书运营专家'（必填）"},

        },

        handler=_set_role_tool,

    ),

    # GStack methodology tools

    ToolSpec(

        id="builtin:office_hours",

        name="产品探索（YC Office Hours）",

        category="productivity",

        risk_level="none",

        allowed_roles=["personal", "project"],

        description="YC风格的深度产品探索：6个强制问题帮助用户厘清需求。当用户说'帮我分析需求'、'产品定位'、'我想做个产品'时使用。",

        parameters={

            "goal": {"type": "string", "description": "用户的需求描述（必填）"},

        },

        handler=_office_hours_tool,

    ),

    ToolSpec(

        id="builtin:review_doc",

        name="审查文档/代码（Review）",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="系统性审查方法论，支持代码审查、设计审查、文档审查。当用户说'帮我审查'、'检查一下'、'Review'、'代码审查'时使用。",

        parameters={

            "type": {"type": "string", "description": "审查类型：general(通用)/code(代码)/design(设计)"},

            "content": {"type": "string", "description": "审查对象内容（可选）"},

        },

        handler=_review_doc_tool,

    ),

    ToolSpec(

        id="builtin:investigate",

        name="根因调查（Investigate）",

        category="productivity",

        risk_level="low",

        allowed_roles=["personal", "project"],

        description="系统化根因排查协议：观察→假设→验证→收敛。当用户说'排查问题'、'调查故障'、'debug'、'为什么出错了'时使用。",

        parameters={

            "issue": {"type": "string", "description": "问题描述（必填）"},

        },

        handler=_investigate_tool,

    ),

    ToolSpec(

        id="builtin:spec",

        name="需求规格化（Spec）",

        category="productivity",

        risk_level="none",

        allowed_roles=["personal", "project"],

        description="将模糊需求转化为结构化规格文档。五阶段方法论：为什么→范围→技术方案→草案→定稿。当用户说'写需求文档'、'写spec'、'需求分析'时使用。",

        parameters={

            "goal": {"type": "string", "description": "用户的需求目标（必填）"},

        },

        handler=_spec_tool,

    ),

    ToolSpec(

        id="builtin:retro",

        name="团队回顾（Retro）",

        category="productivity",

        risk_level="none",

        allowed_roles=["personal", "project"],

        description="团队回顾分析框架：做得好→可以改进→行动项。当用户说'做回顾'、'复盘'、'项目回顾'、'周回顾'时使用。",

        parameters={

            "period": {"type": "string", "description": "回顾周期（可选，默认本周）"},

        },

        handler=_retro_tool,

    ),

    ToolSpec(

        id="builtin:add_admin",

        name="添加企业管理员",

        category="system",

        risk_level="high",

        allowed_roles=["personal", "project"],

        description="添加企业管理员。管理员列表为空时任何人都可添加第一个管理员，之后仅管理员可添加。当用户说'添加管理员'、'设为管理员'时使用。调用时把用户自己的ID传给from参数。",

        parameters={

            "name": {"type": "string", "description": "员工姓名（必填），如'张三'"},

            "from": {"type": "string", "description": "当前用户的ID，从会话上下文获取"},

        },

        handler=_add_admin_tool,

    ),

    ToolSpec(

        id="builtin:remove_admin",

        name="移除企业管理员",

        category="system",

        risk_level="high",

        allowed_roles=["personal", "project"],

        description="移除企业管理员。仅管理员可操作。当用户说'移除管理员'、'删除管理员'时使用。调用时把用户自己的ID传给from参数。",

        parameters={

            "name": {"type": "string", "description": "员工姓名（必填）"},

            "from": {"type": "string", "description": "当前用户的ID，从会话上下文获取"},

        },

        handler=_remove_admin_tool,

    ),


    ToolSpec(
        id="builtin:humanize",
        name="去AI味文本处理",
        category="productivity",
        risk_level="none",
        allowed_roles=["personal", "project"],
        description="去除文本中的AI味和机器人感。检测29种AI写作模式，改写成自然人类语言。用户说'去AI味'、'润色'、'改得更自然'、'去掉机器感'时使用。",
        parameters={
            "text": {"type": "string", "description": "要处理的文本（必填）"},
        },
        handler=_humanize_tool,
    ),
    ToolSpec(
        id="builtin:get_entry_link",
        name="获取入口链接",
        category="productivity",
        risk_level="none",
        allowed_roles=["personal", "project"],
        description="当用户需要打开后台管理、管理员控制台、知识库管理、上传文档入口等管理页面时使用。target可填'admin'管理员控制台、'knowledge'知识库管理、'menu'入口菜单。用户说'后台'、'管理'、'控制台'、'知识库'、'上传文档'、'管理页面'、'管理员页面'、'帮我打开后台'等意图时调用。",
        parameters={
            "target": {"type": "string", "description": "目标页面：'admin'管理员控制台、'knowledge'知识库管理、'menu'入口菜单"},
        },
        handler=_get_entry_link_tool,
    ),
    ToolSpec(
        id="builtin:broadcast_org_message",
        name="组织架构通知群发",
        category="admin",
        risk_level="medium",
        allowed_roles=["personal", "project"],
        description="仅管理员可用。按企业 IM 通讯录组织架构给全体员工或指定部门内已开通企业 AI 助手的员工发送通知消息。用户说“通知全体员工...”“给技术部通知...”等意图时调用。",
        parameters={
            "platform": {"type": "string", "description": "企业 IM 平台，默认 wecom"},
            "user_id": {"type": "string", "description": "发起通知的管理员企业 IM user_id"},
            "target": {"type": "string", "description": "通知范围，例如：全体员工、技术部、部门 ID"},
            "message": {"type": "string", "description": "要发送给员工的通知内容"},
        },
        handler=_broadcast_org_message_tool,
    ),
    ToolSpec(
        id="builtin:query_ratemin_todos",
        name="查询我的业务系统待办",
        category="enterprise-app",
        risk_level="low",
        allowed_roles=["personal", "project"],
        description="查询业务系统软件中的待办和流程通知。普通员工默认查询本人；管理员可以查询指定员工，例如“查询员工甲的业务系统待办”“查李四的外购申请单”。只查询，不发起、不同意、不退回、不处理业务系统流程。",
        parameters={
            "platform": {"type": "string", "description": "企业 IM 平台，默认 wecom"},
            "user_id": {"type": "string", "description": "当前用户企业 IM user_id"},
            "target_user": {"type": "string", "description": "可选。要查询的目标员工姓名或 user_id；普通员工不填，管理员可填“员工甲”之类"},
            "query": {"type": "string", "description": "可选关键词，可按主题、内容、时间、发起人模糊查询"},
            "source_db": {"type": "string", "description": "可选业务系统数据库：business_a 或 business_b"},
            "limit": {"type": "integer", "description": "最多返回条数，默认 20"},
        },
        handler=_query_ratemin_todos_tool,
    ),
    ToolSpec(
        id="builtin:web_search_aggregate",
        name="多源联网搜索",
        category="search",
        risk_level="low",
        allowed_roles=["personal", "project"],
        description="跨多个公开搜索来源聚合结果并去重排序。适合用户要求联网搜索、尽量多找来源、对比多个公开来源、减少单一搜索源不稳定影响时使用。遵守 robots.txt、缓存和限速，不绕过登录、验证码、付费墙或访问控制。",
        parameters={
            "query": {"type": "string", "description": "搜索关键词或问题"},
            "max_results": {"type": "integer", "description": "最多结果数，默认 10，最多 30"},
            "freshness": {"type": "string", "description": "可选时间范围，SearXNG 支持时可填 day/week/month/year"},
            "domains": {"type": "array", "description": "可选限定域名列表，例如 open-meteo.com"},
            "include_sources": {"type": "array", "description": "可选指定来源：Crossref、OpenAlex、arXiv、Tavily、Firecrawl Search、Exa、Brave Search、SerpAPI、GitHub、StackExchange、Hacker News、SearXNG、Bing HTML、AnySearch"},
        },
        handler=_web_search_aggregate_tool,
    ),
    ToolSpec(
        id="builtin:web_research",
        name="互联网综合调研",
        category="search",
        risk_level="low",
        allowed_roles=["personal", "project"],
        description="对公开互联网信息进行综合检索和正文摘取。可使用自托管 SearXNG、结构化开放源，以及可选的 Tavily/Firecrawl Search/Exa/Brave Search/SerpAPI/AnySearch 私有 API；会遵守 robots.txt、缓存和限速。用户要求网上检索、综合资料、对比多个来源、查最新公开信息时优先使用。不会绕过登录、验证码、付费墙或网站访问控制。",
        parameters={
            "query": {"type": "string", "description": "调研主题或搜索关键词"},
            "max_results": {"type": "integer", "description": "搜索结果数量，默认 5，最多 20"},
            "read_top": {"type": "integer", "description": "读取前几个网页正文，默认 3"},
            "freshness": {"type": "string", "description": "可选时间范围，SearXNG 支持时可填 day/week/month/year"},
        },
        handler=_web_research_tool,
    ),
    ToolSpec(
        id="builtin:web_read",
        name="读取公开网页正文",
        category="search",
        risk_level="low",
        allowed_roles=["personal", "project"],
        description="读取公开网页并抽取正文，适合用户发来 URL 要求总结、提炼、对比。默认使用静态抓取；render=true 时尝试 Playwright 渲染动态页面。遵守 robots.txt，不绕过登录、验证码、付费墙或访问控制。",
        parameters={
            "url": {"type": "string", "description": "http/https 网页地址"},
            "max_chars": {"type": "integer", "description": "最多返回字符数，默认 6000"},
            "render": {"type": "boolean", "description": "是否尝试浏览器渲染动态页面，默认 false"},
            "backend": {"type": "string", "description": "读取后端：auto、static、firecrawl、crawl4ai、playwright、jina_reader。默认 auto"},
        },
        handler=_web_read_tool,
    ),
    ToolSpec(
        id="builtin:web_discover_sources",
        name="发现公开信息源",
        category="search",
        risk_level="low",
        allowed_roles=["personal", "project"],
        description="发现网站公开 RSS/Atom、sitemap、API 或数据集入口。适合用户想长期跟踪某网站、行业、新闻、公告、政策时使用，可配合公共数据订阅或知识库入库。",
        parameters={
            "url": {"type": "string", "description": "网站首页 URL；如果没有 URL，可改用 query/topic"},
            "query": {"type": "string", "description": "主题关键词，用于搜索 RSS/sitemap/API/dataset"},
            "max_items": {"type": "integer", "description": "最多返回信息源数量，默认 12"},
        },
        handler=_web_discover_sources_tool,
    ),
    ToolSpec(
        id="builtin:web_research_health",
        name="联网搜索能力诊断",
        category="search",
        risk_level="low",
        allowed_roles=["personal", "project"],
        description="诊断企业 AI 助手当前联网搜索和网页读取能力，包括 SearXNG、Jina、AnySearch、Crawl4AI、Playwright、trafilatura、缓存和 robots 配置。管理员询问搜索能力是否可用、网页读取后端是否启用、为什么搜索差时调用。",
        parameters={},
        handler=_web_research_health_tool,
    ),
    ToolSpec(
        id="builtin:web_random_info",
        name="随机公共信息获取",
        category="search",
        risk_level="low",
        allowed_roles=["personal", "project"],
        description="获取随机公共知识或围绕主题做轻量随机发现，适合用户要求随机资料、拓展视野、找灵感、随机学习材料。",
        parameters={
            "topic": {"type": "string", "description": "可选主题；为空时从公共百科随机获取"},
            "count": {"type": "integer", "description": "数量，默认 3"},
        },
        handler=_web_random_info_tool,
    ),
    ToolSpec(
        id="builtin:query_public_data",
        name="公共数据查询",
        category="public_data",
        risk_level="low",
        allowed_roles=["personal", "project"],
        description="查询公共数据源。支持天气、空气质量、汇率、节假日、RSS、Wikidata、OpenAlex、GDELT、行业监测；货运、航班、供应链价格在配置企业可用数据源后可用。用户询问天气、空气质量、汇率、新闻、节假日、论文、公共知识、舆情、行业动态时调用。",
        parameters={
            "kind": {"type": "string", "description": "数据类型：weather、air_quality、exchange_rate、holiday、rss、wikidata、openalex、gdelt、industry、fred、shipment、flight、supply_price"},
            "query": {"type": "string", "description": "查询关键词、城市、RSS 地址、主题或代码"},
            "params": {"type": "object", "description": "可选参数，例如 base/symbols/country/year/latitude/longitude/url/series_id"},
        },
        handler=_query_public_data_tool,
    ),
    ToolSpec(
        id="builtin:subscribe_public_data",
        name="公共数据订阅",
        category="public_data",
        risk_level="low",
        allowed_roles=["personal", "project"],
        description="为当前用户创建公共数据变化订阅。适用于每天提醒天气、空气质量、汇率、行业新闻、节假日、公共知识源、舆情等；后续状态变化由 AI 助手自动通知用户。",
        parameters={
            "kind": {"type": "string", "description": "数据类型：weather、air_quality、exchange_rate、holiday、rss、wikidata、openalex、gdelt、industry、fred、shipment、flight、supply_price"},
            "query": {"type": "string", "description": "订阅关键词、城市、RSS 地址、主题或代码"},
            "schedule": {"type": "string", "description": "检查频率，例如 every 1d、every 6h、every 30 min"},
            "params": {"type": "object", "description": "可选参数，例如 base/symbols/country/year/latitude/longitude/url/series_id"},
        },
        handler=_subscribe_public_data_tool,
    ),
    ToolSpec(
        id="builtin:list_public_data_subscriptions",
        name="查看公共数据订阅",
        category="public_data",
        risk_level="none",
        allowed_roles=["personal", "project"],
        description="查看当前用户已经创建的公共数据订阅。用户询问我的订阅、公共数据提醒有哪些、取消或核对提醒前先调用。",
        parameters={},
        handler=_list_public_data_subscriptions_tool,
    ),
]





def register_builtin_tools(registry: Any) -> None:

    for tool in BUILTIN_TOOLS:

        registry.register(tool, source="builtin")

