from __future__ import annotations



import json

from datetime import datetime, timedelta

from typing import Any



import logging
from src.models.contracts import Task, TaskDraft, TaskStatus as _TaskStatus

logger = logging.getLogger(__name__)

from src.tools.registry import ToolSpec





def _now_tool(args: dict[str, Any]) -> str:

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")





def _echo_tool(args: dict[str, Any]) -> str:

    return str(args.get("text", ""))





def _create_draft_tool(args: dict[str, Any]) -> str:

    from src.store.database import Database

    from src.store.task_repo import TaskRepository

    repo = TaskRepository(Database.get())

    draft = TaskDraft(

        title=args.get("title", "未命名任务"),

        description=args.get("description", ""),

        project_id=args.get("project_id", "default"),

        assignee_user_id=args.get("assignee"),

        confidence=0.8,

        source_message_ids=[],

    )

    draft_id = repo.save_draft(draft)

    if repo.confirm_draft(draft_id):

        return f"任务已创建并自动确认：{draft.title}"

    return f"任务已创建：{draft.title}（草稿#{draft_id}）"





def _search_knowledge_tool(args: dict[str, Any]) -> str:

    from src.knowledge.gbrain_repo import GbrainKnowledgeRepository

    repo = GbrainKnowledgeRepository()

    query = str(args.get("query", ""))

    if not query:

        return "请提供搜索关键词 (query)"

    user_id = args.get("user_id", "*")

    results = repo.search_accessible(query, user_id, limit=5) if user_id and user_id != "*" else repo.search(query, limit=5)

    if not results:

        return f"未找到关于 '{query}' 的知识条目"

    lines = [f"搜索 '{query}' 找到 {len(results)} 条结果:"]

    for r in results:

        lines.append(f"  [{r.owner_type.value}] {r.content[:120]}")

    return "\n".join(lines)





def _query_tasks_tool(args: dict[str, Any]) -> str:

    from src.store.database import Database

    from src.store.task_repo import TaskRepository

    repo = TaskRepository(Database.get())

    project_id = str(args.get("project_id", ""))

    tasks = repo.list_tasks(project_id=project_id) if project_id else repo.list_tasks()

    if not tasks:

        return "当前无任务" if not project_id else f"空间 {project_id} 中暂无任务"

    lines = [f"任务列表 ({len(tasks)} 个):" if not project_id else f"空间 {project_id} 任务列表 ({len(tasks)} 个):"]

    for t in tasks[:20]:

        extra = ""

        if t.blocked_reason:

            extra = f" [阻塞: {t.blocked_reason}]"

        if t.blocked_by_task_id:

            extra += f" [依赖: {t.blocked_by_task_id}]"

        lines.append(f"  {t.id}: [{t.status.value}] {t.title} @{t.assignee_user_id or '-'}{extra}")

    return "\n".join(lines)





def _attendance_tool(args: dict[str, Any]) -> str:

    from src.tools.attendance_tool import query_attendance

    from src.store.database import Database

    from src.store.task_repo import TaskRepository

    days = int(args.get("days", 7))

    user_id = args.get("user_id", "")

    return query_attendance(user_id, days)





def _leave_tool(args: dict[str, Any]) -> str:

    from src.tools.attendance_tool import query_attendance

    user_id = args.get("user_id", "")

    days = int(args.get("days", 30))

    return query_attendance(user_id, days, query_type="leave")





def _leave_balance_tool(args: dict[str, Any]) -> str:

    from src.tools.attendance_tool import query_leave_balance

    return query_leave_balance(args.get("user_id", ""))





def _dept_attendance_tool(args: dict[str, Any]) -> str:

    from src.tools.dept_tool import query_subordinates

    return query_subordinates(args.get("user_id", ""), "all", int(args.get("days", 7)))





def _subordinate_tool(args: dict[str, Any]) -> str:

    from src.tools.dept_tool import query_subordinate_by_name

    return query_subordinate_by_name(

        args.get("user_id", ""), args.get("name", ""),

        args.get("type", "all"), int(args.get("days", 7))

    )





def _subordinate_balance_tool(args: dict[str, Any]) -> str:

    from src.tools.dept_tool import query_subordinate_balance

    return query_subordinate_balance(args.get("user_id", ""), args.get("name", ""))





def _tushare_tool(args: dict[str, Any]) -> str:

    from src.tools.tushare_mcp import call_tushare

    method = args.get("method", "daily")

    params = {}

    if args.get("code"):

        params["ts_code"] = args["code"]

    if args.get("start"):

        params["start_date"] = args["start"]

    if args.get("end"):

        params["end_date"] = args["end"]

    return call_tushare(method, params)





def _transition_task_tool(args: dict[str, Any]) -> str:

    from src.store.database import Database

    from src.store.task_repo import TaskRepository

    from src.models.contracts import TaskStatus

    repo = TaskRepository(Database.get())

    task_id = args.get("task_id", "")

    status_str = args.get("status", "")

    try:

        status = TaskStatus(status_str)

    except ValueError:

        return f"无效状态：{status_str}，有效值：in_progress/done/blocked/cancelled"

    blocked_reason = args.get("blocked_reason")

    repo.update_task_status(task_id, status, blocked_reason=blocked_reason)

    extra = f" 原因：{blocked_reason}" if blocked_reason else ""

    return f"任务 {task_id} 状态已更新为 {status.value}{extra}"





def _search_tasks_tool(args: dict[str, Any]) -> str:

    from src.store.database import Database

    from src.store.task_repo import TaskRepository

    repo = TaskRepository(Database.get())

    keyword = args.get("keyword", "")

    project_id = args.get("project_id", "")

    limit = int(args.get("limit", 20))

    tasks = repo.search_tasks(keyword=keyword, project_id=project_id, limit=limit)

    if not tasks:

        return f"未找到匹配的任务"

    lines = [f"搜索 '{keyword}' 找到 {len(tasks)} 条结果:"]

    for t in tasks[:limit]:

        lines.append(f"  {t.id}: [{t.status.value}] {t.title} @{t.assignee_user_id or '-'}")

    return "\n".join(lines)





def _task_analytics_tool(args: dict[str, Any]) -> str:

    from src.store.database import Database

    from src.store.task_repo import TaskRepository

    from src.orchestrator.task_analytics import TaskAnalytics

    repo = TaskRepository(Database.get())

    ta = TaskAnalytics(repo)

    space_id = args.get("project_id", "")

    data = ta.project_stats(space_id=space_id) if space_id else ta.dashboard_summary()

    return json.dumps(data, ensure_ascii=False, indent=2)





def _work_journal_tool(args: dict[str, Any]) -> str:

    from src.store.database import Database

    from src.store.task_repo import TaskRepository

    from src.agents.work_journal import WorkJournal

    repo = TaskRepository(Database.get())

    user_id = args.get("user_id", "")

    if not user_id:

        return "请提供用户ID"

    journal = WorkJournal(repo)

    summary = journal.get_summary(user_id)

    return json.dumps(summary, ensure_ascii=False, indent=2)





def _list_spaces_tool(args: dict[str, Any]) -> str:

    from src.store.database import Database

    from src.store.task_repo import TaskRepository

    from src.rooms.space_registry import SpaceRegistry

    repo = TaskRepository(Database.get())

    sr = SpaceRegistry(repo=repo)

    stats = sr.stats()

    return json.dumps(stats, ensure_ascii=False, indent=2)





def _list_knowledge_tool(args: dict[str, Any]) -> str:

    from src.knowledge.gbrain_repo import GbrainKnowledgeRepository

    from src.knowledge.contracts import KnowledgeOwnerType

    kr = GbrainKnowledgeRepository()

    user_id = args.get("user_id", "")

    owner_type = args.get("owner_type", "")

    owner_id = args.get("owner_id", "")

    if user_id:

        results = kr.list_accessible(user_id)

    elif owner_type and owner_id:

        try:

            ot = KnowledgeOwnerType(owner_type)

        except ValueError:

            return f"无效 owner_type: {owner_type}"

        results = kr.list_for_owner(ot, owner_id)

    else:

        results = kr.list_for_owner(KnowledgeOwnerType.ORGANIZATION, "*")

    if not results:

        return "知识库为空"

    lines = [f"知识条目 ({len(results)} 条):"]

    for r in results[:20]:

        lines.append(f"  [{r.owner_type.value}] {r.content[:100]}")

    return "\n".join(lines)





def _add_document_tool(args: dict[str, Any]) -> str:

    """声明文档归属 — add a document to the knowledge base with scope-based ownership."""

    from src.knowledge.acl import resolve_role, Role

    from src.knowledge.gbrain_repo import GbrainKnowledgeRepository

    from src.knowledge.contracts import KnowledgeEntry, KnowledgeOwnerType

    import uuid



    scope = args.get("scope", "personal")

    user_id = args.get("user_id", "")

    title = args.get("title", "未命名文档")

    content = args.get("content", "")

    owner_id = args.get("owner_id", "")



    if not user_id:

        return "请提供用户ID"

    if not content:

        return "请提供文档内容"



    role = resolve_role(user_id)



    scope_requirements: dict[str, Role] = {

        "company": Role.leader,

        "department": Role.leader,

        "project": Role.member,

        "personal": Role.self,

    }

    required_role = scope_requirements.get(scope, Role.self)

    if role < required_role:

        return f"权限不足：当前角色 {role.name}，添加 '{scope}' 范围文档需要 {required_role.name} 权限"



    scope_type_map = {

        "company": "organization",

        "department": "department",

        "project": "project",

        "personal": "personal",

    }

    owner_type_str = scope_type_map.get(scope, "personal")

    owner_type = KnowledgeOwnerType(owner_type_str)

    resolved_owner_id = owner_id or (user_id if scope == "personal" else "*")



    # Get default ACL from the collector's helper

    from src.knowledge.collector import _acl_for_owner_type

    read_roles, write_roles = _acl_for_owner_type(owner_type_str)



    repo = GbrainKnowledgeRepository()

    entry = KnowledgeEntry(

        id=str(uuid.uuid4()),

        owner_type=owner_type,

        owner_id=resolved_owner_id,

        content=content,

        tags=[title],

        metadata={"title": title, "added_by": user_id, "scope": scope},

        read_roles=read_roles,

        write_roles=write_roles,

    )

    repo.save(entry)



    return f"文档 '{title}' 已添加到知识库（归属：{scope}）"





def _register_cloud_drive_tool(args: dict[str, Any]) -> str:

    from src.knowledge.cloud_drive import register_drive

    config = args.get("config", "{}")

    if isinstance(config, str):

        import json

        try:

            config = json.loads(config)

        except json.JSONDecodeError:

            config = {}

    try:

        did = register_drive(

            name=args.get("name", ""),

            driver_type=args.get("driver_type", ""),

            config=config,

            scope=args.get("scope", "organization"),

            scope_id=args.get("scope_id", "*"),

            rclone_remote=args.get("rclone_remote", ""),

            user_id=args.get("user_id", ""),

        )

        return f"云盘 '{args.get('name')}' 已注册 (ID: {did})"

    except (PermissionError, ValueError) as e:

        return str(e)





def _list_cloud_drives_tool(args: dict[str, Any]) -> str:

    from src.knowledge.cloud_drive import list_drives

    return list_drives(

        scope=args.get("scope", ""),

        user_id=args.get("user_id", ""),

    )





def _sync_from_cloud_tool(args: dict[str, Any]) -> str:

    from src.knowledge.cloud_drive import sync_from_cloud

    return sync_from_cloud(

        drive_id=args.get("drive_id", ""),

        remote_path=args.get("remote_path", ""),

        local_path=args.get("local_path", ""),

        user_id=args.get("user_id", ""),

    )





def _delete_cloud_drive_tool(args: dict[str, Any]) -> str:

    from src.knowledge.cloud_drive import delete_drive

    try:

        ok = delete_drive(args.get("drive_id", ""), user_id=args.get("user_id", ""))

        return "云盘已删除" if ok else "云盘不存在"

    except PermissionError as e:

        return str(e)





def _select_role_tool(args: dict[str, Any]) -> str:
    try:
        from src.platform.role_manager import select_role
        query = args.get("query", "")
        if not query:
            return ""
        result = select_role(query)
        role = result["role"]
        out = role.name
        if role.content:
            out += "\n\n" + role.content[:2000]
        return out
    except Exception as e:
        return ""





def _list_roles_tool(args: dict[str, Any]) -> str:

    from src.platform.role_manager import list_roles, list_categories

    category = args.get("category", "")

    if category:

        roles = list_roles(category)

        title = f"{category} 类角色 ({len(roles)} 个):"

    else:

        cats = list_categories()

        roles = list_roles()

        title = f"全部 {len(roles)} 个角色（按领域分类）:"

    lines = [title]

    for r in roles:

        tags = ", ".join(r.tags[:4])

        lines.append(f"  **{r.name}** — {r.description} [{tags}]")

    if not category:

        lines.append(f"\n领域: {', '.join(cats)}")

    return "\n".join(lines)





def _set_role_tool(args: dict[str, Any]) -> str:

    from src.platform.role_manager import get_role

    name = args.get("name", "")

    if not name:

        return "请指定角色名称"

    role = get_role(name)

    if not role:

        return f"未找到角色 '{name}'，请使用 list_roles 查看可用角色"

    lines = [f"已切换到 **{role.name}** ({role.category})"]

    if role.content:

        lines.append(f"\n=== 角色定义: {role.name} ===\n{role.content[:2000]}")

    return "\n".join(lines)





def _office_hours_tool(args: dict[str, Any]) -> str:

    from src.tools.gstack_skills import office_hours

    return office_hours(goal=args.get("goal", ""), context=args.get("context", ""))





def _review_doc_tool(args: dict[str, Any]) -> str:

    from src.tools.gstack_skills import review_doc

    return review_doc(doc_type=args.get("type", "general"), content=args.get("content", ""))





def _investigate_tool(args: dict[str, Any]) -> str:

    from src.tools.gstack_skills import investigate

    return investigate(issue=args.get("issue", ""), context=args.get("context", ""))





def _spec_tool(args: dict[str, Any]) -> str:

    from src.tools.gstack_skills import spec_tool

    return spec_tool(goal=args.get("goal", ""))





def _retro_tool(args: dict[str, Any]) -> str:

    from src.tools.gstack_skills import retro_tool

    return retro_tool(period=args.get("period", "本周"), data=args.get("data", ""))









def _add_admin_tool(args):

    name = args.get("name", "")

    platform = args.get("platform", "wecom")

    from_user = args.get("from", "")

    if not name:

        return "请提供要添加的管理员姓名"

    from src.knowledge.acl import resolve_role, Role

    from src.platform.admin_registry import add_admin, get_admin_ids

    from src.platform.api_wecom import _get



    current_admins = get_admin_ids(platform)

    role = resolve_role(from_user)

    if current_admins and role < Role.admin:

        return "权限不足：仅管理员可添加管理员。请先联系现有管理员添加。"



    try:

        dept_resp = _get("department/list")

        for d in dept_resp.get("department", []):

            users = _get("user/list", f"department_id={d['id']}&fetch_child=1")

            for u in users.get("userlist", []):

                if u.get("name", "") == name:

                    add_admin(platform, u["userid"], name, from_user)

                    return f"已添加 {name} 为企业管理员"

        return f"未找到员工: {name}"

    except Exception as e:

        return f"添加失败: {e}"





def _remove_admin_tool(args):

    name = args.get('name', '')

    platform = args.get('platform', 'wecom')

    if not name:

        return '请提供要移除的管理员姓名'

    from src.platform.admin_registry import remove_admin, list_admins

    for a in list_admins(platform):

        if a['name'] == name or a['user_id'] == name:

            remove_admin(platform, a['user_id'])

            return '已移除管理员: %s' % name

    return '未找到管理员: %s' % name






def _humanize_tool(args):
    from src.tools.humanizer import humanize, analyze_text_style
    text = args.get("text", "")
    if not text:
        return "请提供要处理的文本"
    result = humanize(text)
    style = analyze_text_style(text)
    out = ["去AI味处理结果:", result]
    if style.get("ai_patterns"):
        out.append("")
        out.append("检测到AI模式: " + ", ".join(style["ai_patterns"].keys()))
    return "\n".join(out)


def _generate_report_handler(args):
    from src.tools.document_tool import generate_report
    title = args.get("title", "文档")
    content = args.get("content", "")
    fmt = args.get("format", "docx")
    user_id = args.get("from", "")

    if not content.strip():
        return "请提供文档内容后再生成。请告诉我文档的具体内容、章节和需要包含的信息。"

    # Enrich content using LLM before generating
    _original_len = len(content)
    _enriched = False
    _err = ""
    try:
        from src.config.bootstrap import build_settings_service

        snap = None
        try:
            svc = build_settings_service()
            snap = svc.build_runtime_snapshot()
        except Exception as e:
            _err = f"settings: {e}"

        if snap and snap.llm_profiles:
            for p in snap.llm_profiles:
                if p.enabled:
                    api_base = (p.api_base or "").rstrip("/")
                    if not api_base or not p.api_key:
                        continue
                    import httpx as _httpx
                    prompt_text = ("你是一个专业的文档撰写专家。根据以下内容生成一份格式规范、结构完整的正式文档。"
                                   "要求：有清晰的标题层级、章节划分、条目编号。"
                                   "如果内容中提到了格式要求或模板参考，请严格遵守。"
                                   "直接返回完整的文档内容，不要加额外说明。\n\n" + content)
                    _resp = _httpx.post(api_base + "/chat/completions",
                        headers={"Authorization": "Bearer " + p.api_key},
                        json={"model": p.model_name, "messages": [{"role": "user", "content": prompt_text}], "max_tokens": 4096},
                        timeout=60)
                    if _resp.status_code == 200:
                        enriched = _resp.json()["choices"][0]["message"]["content"]
                        if enriched and len(enriched) > _original_len:
                            content = enriched
                            _enriched = True
                    else:
                        _err = f"API {_resp.status_code}"
                    break
    except Exception as e:
        _err = str(e)

    if _enriched:
        logger.info("Content enriched: %d -> %d chars", _original_len, len(content))
    elif _err:
        logger.warning("Content enrichment skipped: %s", _err)

    result = generate_report(title, content, fmt)
    if result.startswith("文档生成失败") or result.startswith("OfficeCLI"):
        return result
    import os as _os2
    _fn = _os2.path.basename(result)
    return f"文档已生成，点击下载：http://10.12.254.122:18092/api/v1/documents/{_fn}"


def _set_priority_tool(args: dict[str, Any]) -> str:

    from src.store.database import Database

    from src.store.task_repo import TaskRepository

    repo = TaskRepository(Database.get())

    task_id = args.get("task_id", "")

    priority = args.get("priority", "medium")

    if priority not in ("high", "medium", "low"):

        return "优先级必须为 high/medium/low"

    repo.set_priority(task_id, priority)

    return f"任务 {task_id} 优先级已设为 {priority}"





def _send_email_tool(args: dict[str, Any]) -> str:

    from src.tools.email_tool import send_email

    to = args.get("to", "")

    subject = args.get("subject", "")

    body = args.get("body", "")

    cc = args.get("cc")

    return send_email(to=to, subject=subject, body=body, cc=cc)





def _list_emails_tool(args: dict[str, Any]) -> str:

    from src.tools.email_tool import list_inbox

    limit = int(args.get("limit", 10))

    return list_inbox(limit=limit)





def _search_emails_tool(args: dict[str, Any]) -> str:

    from src.tools.email_tool import search_emails

    query = args.get("query", "")

    return search_emails(query=query)





def _get_email_tool(args: dict[str, Any]) -> str:

    from src.tools.email_tool import get_email

    uid = args.get("uid", "")

    return get_email(uid=uid)





def _merge_pdfs_tool(args: dict[str, Any]) -> str:

    from src.tools.pdf_tool import merge_pdfs

    paths = args.get("paths", "").split(",")

    output = args.get("output", "merged.pdf")

    return merge_pdfs([p.strip() for p in paths], output)





def _split_pdf_tool(args: dict[str, Any]) -> str:

    from src.tools.pdf_tool import split_pdf

    path = args.get("path", "")

    pages = args.get("pages", "")

    output = args.get("output", "split.pdf")

    return split_pdf(path, pages, output)





def _compress_pdf_tool(args: dict[str, Any]) -> str:

    from src.tools.pdf_tool import compress_pdf

    path = args.get("path", "")

    output = args.get("output", "compressed.pdf")

    return compress_pdf(path, output)





def _protect_pdf_tool(args: dict[str, Any]) -> str:

    from src.tools.pdf_tool import protect_pdf

    path = args.get("path", "")

    password = args.get("password", "")

    output = args.get("output", "protected.pdf")

    return protect_pdf(path, password, output)





def _ddg_search_tool(args: dict[str, Any]) -> str:

    import urllib.request, urllib.parse, json

    query = args.get("query", "")

    if not query:

        return "请提供搜索关键词"

    try:

        url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(query)}&format=json&no_html=1"

        resp = json.loads(urllib.request.urlopen(url, timeout=15).read())

        abstract = resp.get("AbstractText", "")

        results = resp.get("Results", []) or resp.get("RelatedTopics", [])

        lines = [f"DuckDuckGo 搜索结果: {query}"]

        if abstract:

            lines.append(f"摘要: {abstract}")

        for r in results[:8]:

            if isinstance(r, dict) and "Text" in r:

                lines.append(f"  - {r.get('Text','')}")

            elif isinstance(r, dict) and "Result" in r:

                lines.append(f"  - {r.get('Result','')}")

        return "\n".join(lines) if len(lines) > 1 else f"未找到关于 '{query}' 的结果"

    except Exception as e:

        return f"DuckDuckGo 搜索失败: {e}"





def _contact_search_tool(args: dict[str, Any]) -> str:

    from src.platform import contact_search

    query = args.get("query", "")

    if not query:

        return "请提供搜索关键词，如姓名、手机号"

    return contact_search(query)





def _calendar_agenda_tool(args: dict[str, Any]) -> str:

    from src.platform import calendar_agenda

    days = int(args.get("days", 7))

    return calendar_agenda(days)





def _doc_search_tool(args: dict[str, Any]) -> str:

    from src.platform import doc_search

    query = args.get("query", "")

    if not query:

        return "请提供搜索关键词"

    return doc_search(query)





def _approval_list_tool(args: dict[str, Any]) -> str:

    from src.platform import approval_list

    status = args.get("status", "pending")

    return approval_list(status)





def _calendar_create_tool(args: dict[str, Any]) -> str:

    from src.platform import calendar_create

    summary = args.get("summary", "")

    start = args.get("start", "")

    end = args.get("end", "")

    if not summary or not start or not end:

        return "请提供日程标题、开始时间和结束时间"

    return calendar_create(summary, start, end)





def _create_doc_tool(args: dict[str, Any]) -> str:

    from src.platform import create_doc

    title = args.get("title", "")

    content = args.get("content", "")

    if not title:

        return "请提供文档标题"

    return create_doc(title, content)





def _list_meetings_tool(args: dict[str, Any]) -> str:

    from src.platform import list_meetings

    return list_meetings()





def _create_meeting_tool(args: dict[str, Any]) -> str:

    from src.platform import create_meeting

    title = args.get("title", "")

    start = args.get("start", "")

    end = args.get("end", "")

    attendees = args.get("attendees", "")

    if not title or not start or not end:

        return "请提供会议标题、开始时间和结束时间"

    return create_meeting(title, start, end, attendees)





def _who_is_admin_tool(args: dict[str, Any]) -> str:

    from src.platform import who_is_admin

    return who_is_admin()





def _who_is_leader_tool(args: dict[str, Any]) -> str:

    from src.platform import who_is_leader

    return who_is_leader()





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

        description="部门负责人通过姓名查询特定下属员工的考勤或审批记录。当负责人说'马戈的考勤'或'韩斌的请假'或'张三上周的考勤'或'李四的审批'等时，使用此工具。name参数填员工姓名，type参数填'attendance'考勤或'approval'审批。",

        parameters={

            "user_id": {"type": "string", "description": "当前用户的微信ID（必填）"},

            "name": {"type": "string", "description": "员工姓名（必填，如'马戈'、'韩斌'）"},

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

            "name": {"type": "string", "description": "员工姓名（必填），如'马戈'"},

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
]





def register_builtin_tools(registry: Any) -> None:

    for tool in BUILTIN_TOOLS:

        registry.register(tool, source="builtin")

