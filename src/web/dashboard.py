from __future__ import annotations

import csv
import html
import io
import json
import logging
import os
import re
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from src.analysis.role_analyzer import GroupMessageAnalyzer, RoleAnalyzer
from src.isolation.file_store import IsolatedFileStore
from src.knowledge.contracts import KnowledgeEntry, KnowledgeOwnerType
from src.knowledge.collector import KnowledgeCollector
from src.knowledge.linking import build_knowledge_open_url
from src.tools.knowledge_tools import owner_type_label
from src.knowledge.repository_factory import build_knowledge_repository
from src.models.contracts import Task, TaskStatus
from src.pool.agent_pool import AgentPool
from src.rooms.space_registry import SpaceRegistry
from src.store.database import Database
from src.store.task_repo import TaskRepository
from src.web.document_paths import resolve_document_download_path
from src.web.admin_auth import require_admin_context_from_request, require_console_context_from_request, require_user_context_from_request
from src.web.middleware import add_request_id, check_rate_limit, require_auth

logger = logging.getLogger(__name__)

app = FastAPI(title="Ant Colony API", version="0.3.0")

_PUBLIC_PATHS = {"/", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json", "/admin/console", "/knowledge/manage", "/knowledge/user"}
_PUBLIC_PREFIXES = ("/api/v1/user/", "/api/v1/site/ratemin/", "/api/v1/web-search/")
_ADMIN_API_PREFIX = "/api/v1/admin/"
MAX_UPLOAD_BYTES = int(os.environ.get("ANT_COLONY_MAX_FILE_BYTES", str(50 * 1024 * 1024)))


@app.middleware("http")
async def auth_and_rate_limit(request: Request, call_next):
    try:
        if (
            request.url.path not in _PUBLIC_PATHS
            and not request.url.path.startswith(_ADMIN_API_PREFIX)
            and not request.url.path.startswith(_PUBLIC_PREFIXES)
        ):
            require_auth(request)
        check_rate_limit(request)
    except HTTPException as e:
        return Response(content=json.dumps({"error": str(e.detail)}), status_code=e.status_code, media_type="application/json")
    response = await call_next(request)
    response.headers["X-Request-ID"] = add_request_id(request)
    return response

repo: TaskRepository | None = None
_group_msg_analyzer: GroupMessageAnalyzer | None = None
agent_pool = AgentPool()
_space_registry: SpaceRegistry | None = None
_knowledge_repo: Any = None
_warm_store: Any = None
_cold_store: Any = None


def get_repo() -> TaskRepository:
    global repo
    if repo is None:
        db = Database.get("./data/ant-colony.db")
        repo = TaskRepository(db)
    return repo


def get_space_registry() -> SpaceRegistry:
    global _space_registry
    if _space_registry is None:
        _space_registry = SpaceRegistry(repo=get_repo())
    return _space_registry


def get_knowledge_repo() -> Any:
    global _knowledge_repo
    if _knowledge_repo is None:
        _knowledge_repo = build_knowledge_repository()
    return _knowledge_repo


def get_group_analyzer() -> GroupMessageAnalyzer:
    global _group_msg_analyzer
    if _group_msg_analyzer is None:
        _group_msg_analyzer = GroupMessageAnalyzer(RoleAnalyzer())
    return _group_msg_analyzer


def _model_payload(req: BaseModel) -> dict[str, Any]:
    if hasattr(req, "model_dump"):
        return req.model_dump()
    return req.dict()


def _require_leave_manager_context(request: Request) -> dict[str, Any]:
    context = require_console_context_from_request(request)
    if context.get("role") not in {"admin", "hr_specialist"}:
        raise HTTPException(403, "当前用户没有审批假期管理权限")
    return context


# ---- Request models ----

class ConfirmRequest(BaseModel):
    draft_id: int

class DismissRequest(BaseModel):
    draft_id: int

class TransitionRequest(BaseModel):
    task_id: str
    status: str
    blocked_reason: str | None = None

class DismissReminderRequest(BaseModel):
    reminder_id: int

class DependencyRequest(BaseModel):
    task_id: str
    blocked_by_task_id: str

class SpaceRequest(BaseModel):
    space_id: str
    name: str = ""
    space_type: str = "project"
    description: str = ""
    members: list[str] = []

class SpaceMemberRequest(BaseModel):
    space_id: str
    user_id: str


class SpaceLinkRequest(BaseModel):
    source_space_id: str
    target_space_id: str


class PlatformBotActivationRequest(BaseModel):
    credentials: dict[str, str] = {}
    activated_by: str = ""
    display_name: str = ""
    visibility_scope: str = "all"
    auto_permissions: list[str] = []


class WeComMcpConfigRequest(BaseModel):
    doc_mcp_url: str = ""
    todo_mcp_url: str = ""


class EmployeeBotActivationRequest(BaseModel):
    platform: str = "wecom"
    user_id: str
    display_name: str = ""
    scope: str = "personal"
    permissions: list[str] = []
    notify: bool = True
    status: str = "active"


class EmployeeBotBatchRequest(BaseModel):
    platform: str = "wecom"
    user_ids: list[str] = []
    display_name: str = ""
    status: str = "active"
    notify: bool = True


class AssistantProfileAdminRequest(BaseModel):
    platform: str = "wecom"
    user_id: str
    assistant_name: str = ""
    user_call_name: str = ""
    role_id: str = ""


class HrSpecialistRequest(BaseModel):
    platform: str = "wecom"
    user_id: str
    enabled: bool = True


class HrSpecialistBatchRequest(BaseModel):
    platform: str = "wecom"
    user_ids: list[str] = []
    enabled: bool = True


class OrganizationBroadcastRequest(BaseModel):
    platform: str = "wecom"
    target: str
    message: str


class RateminIngestRequest(BaseModel):
    platform: str = "wecom"
    events: list[dict[str, Any]] = []


class RateminCurrentIngestRequest(BaseModel):
    platform: str = "wecom"
    source_databases: list[str] = []
    events: list[dict[str, Any]] = []


class RateminUserIngestRequest(BaseModel):
    platform: str = "wecom"
    auto_bind: bool = True
    users: list[dict[str, Any]] = []


class RateminBindRequest(BaseModel):
    source_db: str
    rate_oper_id: str = ""
    rate_login_name: str = ""
    rate_display_name: str = ""
    platform: str = "wecom"
    im_user_id: str
    im_display_name: str = ""


class LeaveNegativeProbeRequest(BaseModel):
    platform: str = "wecom"
    user_id: str
    vacation_id: int
    negative_duration: int = -86400
    confirm_live_write: bool = False


class LeaveBalanceTargetRequest(BaseModel):
    platform: str = "wecom"
    user_id: str
    vacation_id: int
    vacation_name: str = ""
    target_leftduration: int
    time_attr: int = 1
    reason: str
    allow_local_negative: bool = False


class LeaveWorkflowNoticeRequest(BaseModel):
    template_id: str
    notice_text: str = ""
    apply_update: bool = False


class LeavePolicyRequest(BaseModel):
    platform: str = "wecom"
    vacation_id: int
    vacation_name: str = ""
    leave_kind: str = ""
    advance_seconds: int = 0
    time_attr: int = 1
    overtime_credit: bool = False


class ModelProfileRequest(BaseModel):
    profile_id: str
    provider: str = "openai_compatible"
    sdk_format: str = "openai"
    display_name: str = ""
    api_base: str = ""
    api_key: str = ""
    model_name: str = ""
    max_tokens: int = 4096
    timeout_seconds: int = 120
    enabled: bool = True


class ModelDiscoverRequest(BaseModel):
    provider: str = "openai"
    sdk_format: str = "openai"
    api_base: str = ""
    api_key: str = ""


class ModelDefaultRequest(BaseModel):
    profile_id: str


class MailAccountRequest(BaseModel):
    account_id: str = ""
    account_label: str = ""
    platform: str = "wecom"
    user_id: str = ""
    user_name: str = ""
    email_address: str = ""
    protocol: str = "imap"
    imap_host: str = ""
    imap_port: int = 993
    imap_ssl: bool = True
    encryption: str = ""
    username: str = ""
    password: str = ""
    folder: str = "INBOX"
    poll_interval_minutes: int = 1
    enabled: bool = True


class MailAccountStatusRequest(BaseModel):
    account_id: str = ""
    platform: str = "wecom"
    user_id: str = ""
    user_name: str = ""
    enabled: bool = True


class MailAccountInferRequest(BaseModel):
    platform: str = "wecom"
    user_id: str = ""
    user_name: str = ""
    email_address: str = ""


class PublicDataSubscriptionRequest(BaseModel):
    kind: str
    query: str = ""
    schedule: str = "every 1d"
    params: dict[str, Any] = {}


class PublicDataSourceRequest(BaseModel):
    kind: str
    label: str = ""
    source: str = ""
    url: str = ""
    method: str = "GET"
    type: str = "json"
    headers: dict[str, str] = {}
    params: dict[str, str] = {}
    body: dict[str, str] = {}
    fields: list[str] = []
    secret: str = ""
    enabled: bool = True
    notes: str = ""


class PublicDataSourceTestRequest(BaseModel):
    kind: str
    query: str = ""
    params: dict[str, Any] = {}


class IntegrationTestRequest(BaseModel):
    integration_id: str
    query: str = ""


class SubscriptionStatusRequest(BaseModel):
    enabled: bool

class KnowledgeCreateRequest(BaseModel):
    id: str
    owner_type: str
    owner_id: str
    content: str
    tags: list[str] = []

class KnowledgeSearchRequest(BaseModel):
    query: str
    user_id: str = ""
    space_id: str = ""
    limit: int = 20

class KnowledgeCollectRequest(BaseModel):
    url: str = ""
    text: str = ""
    title: str = ""
    owner_type: str = "auto"
    owner_id: str = ""
    tags: list[str] = []
    user_id: str = ""
    space_id: str = ""
    platform: str = "wecom"


class KnowledgeUpdateRequest(BaseModel):
    content: str
    title: str = ""
    tags: list[str] = []
    user_id: str = ""
    platform: str = "wecom"


class KnowledgePromoteRequest(BaseModel):
    entry_id: str
    target_owner_type: str
    target_owner_id: str
    new_entry_id: str = ""
    user_id: str = ""
    platform: str = "wecom"


class KnowledgeTransferRequest(BaseModel):
    entry_id: str
    action: str = "copy"
    target_owner_type: str
    target_owner_id: str
    new_entry_id: str = ""
    user_id: str = ""
    platform: str = "wecom"


class FileDeleteRequest(BaseModel):
    user_id: str
    space_id: str
    filename: str


# ---- File store ----

_file_store: IsolatedFileStore | None = None


def _get_file_store() -> IsolatedFileStore:
    global _file_store
    if _file_store is None:
        _file_store = IsolatedFileStore("./data/files")
    return _file_store


# ---- API routes ----

@app.get("/api/v1/tasks")
def list_tasks(space_id: str = ""):
    r = get_repo()
    return {"tasks": [_task_to_dict(t) for t in r.list_tasks(project_id=space_id)]}

@app.get("/api/v1/tasks/search")
def search_tasks(q: str = "", space_id: str = "", limit: int = 50):
    r = get_repo()
    return {"tasks": [_task_to_dict(t) for t in r.search_tasks(keyword=q, project_id=space_id, limit=limit)]}

# ---- System Health ----

_start_time = time.time()

@app.get("/api/v1/health")
def system_health():
    r = get_repo()
    tasks = r.list_tasks()
    total_tasks = len(tasks)
    blocked = sum(1 for t in tasks if t.status.value == "blocked")
    in_progress = sum(1 for t in tasks if t.status.value == "in_progress")
    return {
        "status": "healthy",
        "service": "ant-colony-dashboard",
        "uptime_seconds": round(time.time() - _start_time, 1),
        "db": "connected",
        "tasks": {"total": total_tasks, "blocked": blocked, "in_progress": in_progress},
        "spaces": get_space_registry().stats(),
        "knowledge": get_knowledge_repo().stats() if _knowledge_repo else {},
        "agents": agent_pool.stats(),
    }


@app.get("/api/v1/web-search/more", response_class=HTMLResponse)
def web_search_more_page(q: str = "", page: int = 1, page_size: int = 20):
    query = (q or "").strip()
    if not query:
        return HTMLResponse(
            "<!doctype html><html><head><meta charset=\"utf-8\"><title>搜索结果</title></head>"
            "<body><p>缺少搜索关键词。</p></body></html>",
            status_code=400,
        )
    safe_page = max(1, int(page or 1))
    safe_page_size = max(1, min(int(page_size or 20), 20))
    from src.tools.web_research_service import web_search_aggregate_page_cached

    text = web_search_aggregate_page_cached(query, page=safe_page, page_size=safe_page_size)
    escaped = html.escape(text)
    linked = re.sub(
        r"(https?://[^\s<]+)",
        r'<a href="\1" target="_blank" rel="noopener noreferrer">\1</a>',
        escaped,
    )
    title = html.escape(f"{query} - 第 {safe_page} 页")
    return HTMLResponse(
        f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    body {{ margin: 0; background: #f7f8fb; color: #202124; font-family: "Google Sans", "Noto Sans SC", Arial, sans-serif; }}
    main {{ max-width: 980px; margin: 0 auto; padding: 28px 18px 48px; }}
    .card {{ background: #fff; border: 1px solid #e8eaed; border-radius: 18px; box-shadow: 0 8px 26px rgba(60, 64, 67, .10); overflow: hidden; }}
    header {{ padding: 22px 24px; border-bottom: 1px solid #eef0f4; }}
    h1 {{ margin: 0; font-size: 22px; line-height: 1.35; font-weight: 700; }}
    .meta {{ margin-top: 8px; color: #5f6368; font-size: 14px; }}
    pre {{ white-space: pre-wrap; word-break: break-word; margin: 0; padding: 22px 24px; font-size: 15px; line-height: 1.75; font-family: "Noto Sans SC", Arial, sans-serif; }}
    a {{ color: #1967d2; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <main>
    <section class="card">
      <header>
        <h1>联网检索结果</h1>
        <div class="meta">关键词：{html.escape(query)}；当前第 {safe_page} 页</div>
      </header>
      <pre>{linked}</pre>
    </section>
  </main>
</body>
</html>"""
    )

@app.get("/api/v1/drafts")
def list_drafts(space_id: str = ""):
    r = get_repo()
    return {"drafts": r.list_drafts(project_id=space_id, status="pending")}

@app.get("/api/v1/messages")
def list_messages(space_id: str = "", q: str = "", since: str = "", limit: int = 50):
    r = get_repo()
    return {"messages": r.list_messages(space_id=space_id, keyword=q, since=since, limit=limit)}

@app.get("/api/v1/reminders")
def list_reminders(space_id: str = "", include_dismissed: bool = False):
    r = get_repo()
    return {"reminders": r.list_reminders(space_id=space_id, include_dismissed=include_dismissed)}

@app.get("/api/v1/blocked")
def list_blocked(space_id: str = ""):
    r = get_repo()
    tasks = r.list_tasks(project_id=space_id)
    blocked = [t for t in tasks if t.status == TaskStatus.BLOCKED]
    return {"blocked": [{"space_id": t.project_id, "task_id": t.id, "reason": t.blocked_reason} for t in blocked]}

@app.put("/api/v1/confirm")
def confirm_draft(req: ConfirmRequest):
    r = get_repo()
    task = r.confirm_draft(req.draft_id)
    if task is None:
        raise HTTPException(404, f"Draft {req.draft_id} not found or already confirmed")
    return {"task_id": task.id, "title": task.title, "status": task.status.value}

@app.put("/api/v1/dismiss")
def dismiss_draft(req: DismissRequest):
    r = get_repo()
    r.dismiss_draft(req.draft_id)
    return {"draft_id": req.draft_id, "status": "dismissed"}

@app.put("/api/v1/transition")
def transition_task(req: TransitionRequest):
    try:
        status = TaskStatus(req.status)
    except ValueError:
        raise HTTPException(400, f"Invalid status: {req.status}")
    if status not in (TaskStatus.IN_PROGRESS, TaskStatus.DONE, TaskStatus.BLOCKED, TaskStatus.CANCELLED):
        raise HTTPException(400, f"Cannot transition to {req.status}")
    r = get_repo()
    r.update_task_status(req.task_id, status, blocked_reason=req.blocked_reason)
    return {"task_id": req.task_id, "status": req.status, "action": "transition", "reason": req.blocked_reason}

@app.put("/api/v1/reminder/dismiss")
def dismiss_reminder(req: DismissReminderRequest):
    r = get_repo()
    r.dismiss_reminder(req.reminder_id)
    return {"reminder_id": req.reminder_id, "status": "dismissed"}

@app.put("/api/v1/dependency")
def set_dependency(req: DependencyRequest):
    r = get_repo()
    if req.task_id == req.blocked_by_task_id:
        raise HTTPException(400, "Task cannot depend on itself")
    r.set_dependency(req.task_id, req.blocked_by_task_id)
    return {"task_id": req.task_id, "blocked_by_task_id": req.blocked_by_task_id}


@app.get("/api/v1/roles")
def list_roles(space_id: str = ""):
    r = get_repo()
    msgs = r.list_messages(space_id=space_id, limit=500)
    ga = get_group_analyzer()
    summary = ga.summarize(msgs)
    return {"roles": summary}

@app.get("/api/v1/agents")
def list_agents():
    return {"stats": agent_pool.stats(), "agents": agent_pool.list_agents()}


@app.get("/api/v1/platform/bots")
def list_platform_bots():
    from src.platform.activation_service import list_platform_bot_statuses

    return {"platforms": list_platform_bot_statuses()}


@app.post("/api/v1/platform/bots/{platform}/activate")
def activate_platform_bot_api(platform: str, req: PlatformBotActivationRequest):
    from src.platform.activation_service import activate_platform_bot

    try:
        result = activate_platform_bot(
            platform=platform,
            credentials=req.credentials,
            activated_by=req.activated_by,
            display_name=req.display_name,
            visibility_scope=req.visibility_scope,
            auto_permissions=req.auto_permissions,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {
        "platform": result.platform,
        "enabled": result.enabled,
        "managed_by_platform": result.managed_by_platform,
        "configured_keys": result.configured_keys,
        "visibility_scope": result.visibility_scope,
        "display_name": result.display_name,
        "auto_permissions": result.auto_permissions,
        "restart_required": result.restart_required,
        "next_action": result.next_action,
        "credential_sources": result.credential_sources,
    }


@app.post("/api/v1/admin/refresh-token")
def admin_refresh_token(request: Request):
    """Accept a possibly-expired but HMAC-valid token, return a fresh one."""
    old_token = (
        request.query_params.get("admin_token")
        or request.headers.get("X-Admin-Token")
        or ""
    )
    if not old_token:
        raise HTTPException(401, "缺少管理员访问令牌")
    from src.web.admin_auth import decode_and_refresh_admin_token
    new_token = decode_and_refresh_admin_token(token=old_token)
    return {"admin_token": new_token}


@app.get("/api/v1/admin/profile")
def admin_profile(request: Request):
    context = require_console_context_from_request(request)
    from src.knowledge.acl import resolve_role, visible_scopes
    from src.platform.org_graph import OrgGraphService

    role = resolve_role(context["user_id"], platform=context["platform"])
    graph = OrgGraphService()
    profile = graph.get_user_profile(context["platform"], context["user_id"]) or {}
    return {
        **context,
        "role": context.get("role", "admin"),
        "knowledge_role": role.name,
        "name": profile.get("name", ""),
        "departments": profile.get("departments", []),
        "leader_departments": profile.get("leader_departments", []),
        "visible_scopes": [
            {"owner_type": owner_type, "owner_id": owner_id}
            for owner_type, owner_id in visible_scopes(role, context["user_id"], platform=context["platform"])
        ],
        "can_activate_bots": context.get("role") == "admin",
        "can_import_company_guides": context.get("role") == "admin" and role.value >= 4,
        "can_manage_knowledge": True,
        "can_manage_leave": context.get("role") in {"admin", "hr_specialist"},
        "can_manage_platform": context.get("role") == "admin",
    }


@app.get("/api/v1/admin/platform/bots")
def admin_list_platform_bots(request: Request):
    require_admin_context_from_request(request)
    return list_platform_bots()


@app.post("/api/v1/admin/platform/bots/{platform}/activate")
def admin_activate_platform_bot(platform: str, req: PlatformBotActivationRequest, request: Request):
    context = require_admin_context_from_request(request)
    req.activated_by = req.activated_by or context["user_id"]
    return activate_platform_bot_api(platform, req)


@app.get("/api/v1/admin/wecom/mcp/status")
def admin_wecom_mcp_status(request: Request, discover: bool = False):
    require_admin_context_from_request(request)
    from src.platform.wecom_robot_mcp_provider import get_wecom_robot_mcp_status

    return get_wecom_robot_mcp_status(discover=discover)


@app.post("/api/v1/admin/wecom/mcp/config")
def admin_wecom_mcp_config(req: WeComMcpConfigRequest, request: Request):
    require_admin_context_from_request(request)
    from src.platform.wecom_robot_mcp_provider import save_wecom_robot_mcp_urls

    return save_wecom_robot_mcp_urls(
        doc_url=req.doc_mcp_url,
        todo_url=req.todo_mcp_url,
    )


@app.post("/api/v1/admin/projects/register")
def admin_register_project(request: Request, name: str = Form(...), space_id: str = Form(""), members: str = Form("")):
    context = require_admin_context_from_request(request)
    registry = get_space_registry()
    sid = space_id.strip() or f"project-{context['user_id']}-{int(time.time())}"
    member_list = [m.strip() for m in (members or "").split(",") if m.strip()]
    if not member_list:
        member_list = [context["user_id"]]
    registry.register(sid, name=name.strip() or "未命名项目", space_type="project", members=member_list)
    from src.platform.org_graph import OrgGraphService
    try:
        OrgGraphService().sync_if_stale(context["platform"])
    except Exception:
        pass
    return {"space_id": sid, "name": name.strip(), "members": member_list, "registered": True}


@app.get("/api/v1/admin/employee-bots")
def admin_list_employee_bots(request: Request, platform: str = "", limit: int = 200):
    require_admin_context_from_request(request)
    from src.platform.employee_bot_service import list_employee_bot_assignments

    return {"assignments": list_employee_bot_assignments(platform=platform, limit=limit)}


@app.get("/api/v1/admin/users")
def admin_user_details(request: Request, platform: str = "", sync: bool = True, search: str = ""):
    context = require_console_context_from_request(request)
    from src.platform.user_management_service import list_admin_user_details

    result = list_admin_user_details(platform=platform or context["platform"], sync=sync)
    if search and result.get("users"):
        term = search.lower()
        result["users"] = [
            u for u in result["users"]
            if term in (u.get("name") or "").lower() or term in (u.get("user_id") or "").lower() or term in (u.get("department_path") or "").lower()
        ]
    return result


@app.get("/api/v1/admin/hr-specialists")
def admin_list_hr_specialists(request: Request, platform: str = "wecom"):
    context = require_admin_context_from_request(request)
    from src.platform.hr_specialist_service import list_hr_specialists

    return {"specialists": list_hr_specialists(platform=platform or context["platform"])}


@app.post("/api/v1/admin/hr-specialists")
def admin_set_hr_specialist(req: HrSpecialistRequest, request: Request):
    context = require_admin_context_from_request(request)
    from src.platform.hr_specialist_service import set_hr_specialist

    try:
        return {
            "specialist": set_hr_specialist(
                platform=req.platform or context["platform"],
                user_id=req.user_id,
                enabled=req.enabled,
                granted_by=context["user_id"],
            )
        }
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/v1/admin/hr-specialists/batch")
def admin_batch_hr_specialists(req: HrSpecialistBatchRequest, request: Request):
    context = require_admin_context_from_request(request)
    from src.platform.hr_specialist_service import bulk_set_hr_specialists

    return bulk_set_hr_specialists(
        platform=req.platform or context["platform"],
        user_ids=req.user_ids,
        enabled=req.enabled,
        granted_by=context["user_id"],
    )


@app.post("/api/v1/admin/users/assistant-profile")
def admin_save_user_assistant_profile(req: AssistantProfileAdminRequest, request: Request):
    context = require_admin_context_from_request(request)
    from src.gateway import provider_outbound
    from src.platform.assistant_profile_service import build_profile_update_notice, save_assistant_profile

    try:
        platform = req.platform or context["platform"]
        profile = save_assistant_profile(
            platform=platform,
            user_id=req.user_id,
            assistant_name=req.assistant_name,
            user_call_name=req.user_call_name,
            role_id=req.role_id,
        )
        notify_status = "not_requested"
        if req.user_id:
            notify_status = "sent" if provider_outbound.send_platform_text(platform, req.user_id, build_profile_update_notice(profile)) else "send_failed"
        return {
            "profile": profile,
            "notify_status": notify_status,
        }
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete("/api/v1/admin/users/assistant-profile/{platform}/{user_id}")
def admin_delete_user_assistant_profile(platform: str, user_id: str, request: Request):
    require_admin_context_from_request(request)
    from src.platform.assistant_profile_service import delete_assistant_profile

    return delete_assistant_profile(platform=platform, user_id=user_id)


@app.get("/api/v1/admin/entry-menu")
def admin_entry_menu(request: Request):
    context = require_admin_context_from_request(request)
    from src.gateway.entry_links import build_platform_entry_menu

    return build_platform_entry_menu(context["platform"], context["user_id"], is_admin=True)


@app.get("/api/v1/admin/entry-payloads")
def admin_entry_payloads(request: Request):
    context = require_admin_context_from_request(request)
    from src.gateway.entry_links import build_platform_entry_payloads

    return build_platform_entry_payloads(context["platform"], context["user_id"], is_admin=True)


@app.post("/api/v1/admin/employee-bots/activate")
def admin_activate_employee_bot(req: EmployeeBotActivationRequest, request: Request):
    context = require_admin_context_from_request(request)
    from src.platform.employee_bot_service import activate_employee_bot

    try:
        assignment = activate_employee_bot(
            platform=req.platform,
            user_id=req.user_id,
            display_name=req.display_name,
            scope=req.scope,
            permissions=req.permissions,
            activated_by=context["user_id"],
            notify=req.notify,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"assignment": assignment}


@app.post("/api/v1/admin/employee-bots/deactivate")
def admin_deactivate_employee_bot(req: EmployeeBotActivationRequest, request: Request):
    context = require_admin_context_from_request(request)
    from src.platform.employee_bot_service import deactivate_employee_bot

    try:
        assignment = deactivate_employee_bot(platform=req.platform, user_id=req.user_id, updated_by=context["user_id"])
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"assignment": assignment}


@app.post("/api/v1/admin/employee-bots/welcome")
def admin_send_employee_bot_welcome(req: EmployeeBotActivationRequest, request: Request):
    require_admin_context_from_request(request)
    from src.platform.employee_bot_service import send_employee_bot_welcome

    try:
        return send_employee_bot_welcome(platform=req.platform, user_id=req.user_id, display_name=req.display_name)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/v1/admin/employee-bots/rename")
def admin_rename_employee_bot(request: Request, platform: str = Form(...), user_id: str = Form(...), display_name: str = Form("")):
    require_admin_context_from_request(request)
    from src.platform.employee_bot_service import update_employee_bot_name

    return update_employee_bot_name(platform=platform, user_id=user_id, display_name=display_name)


@app.post("/api/v1/admin/employee-bots/status")
def admin_set_employee_bot_status(req: EmployeeBotActivationRequest, request: Request):
    context = require_admin_context_from_request(request)
    from src.platform.employee_bot_service import activate_employee_bot, set_employee_bot_status

    target_status = str(req.status or "").strip().lower() or "active"
    if target_status == "active":
        assignment = activate_employee_bot(
            platform=req.platform,
            user_id=req.user_id,
            display_name=req.display_name,
            activated_by=context["user_id"],
            notify=req.notify,
        )
    else:
        assignment = set_employee_bot_status(platform=req.platform, user_id=req.user_id, status=target_status, updated_by=context["user_id"])
    return {"assignment": assignment}


@app.post("/api/v1/admin/employee-bots/batch")
def admin_batch_employee_bots(req: EmployeeBotBatchRequest, request: Request):
    context = require_admin_context_from_request(request)
    from src.platform.employee_bot_service import activate_employee_bot, set_employee_bot_status

    results = []
    for user_id in req.user_ids:
        if not str(user_id).strip():
            continue
        if req.status == "active":
            item = activate_employee_bot(
                platform=req.platform,
                user_id=str(user_id),
                display_name=req.display_name,
                activated_by=context["user_id"],
                notify=req.notify,
            )
        else:
            item = set_employee_bot_status(platform=req.platform, user_id=str(user_id), status=req.status, updated_by=context["user_id"])
        results.append(item)
    return {"updated": len(results), "results": results}


@app.post("/api/v1/admin/organization/broadcast")
def admin_broadcast_organization(req: OrganizationBroadcastRequest, request: Request):
    context = require_admin_context_from_request(request)
    from src.platform.organization_broadcast_service import OrganizationBroadcastError, broadcast_to_organization

    try:
        return broadcast_to_organization(
            platform=req.platform,
            sender_user_id=context["user_id"],
            target=req.target,
            message=req.message,
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except OrganizationBroadcastError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/v1/site/ratemin/ingest")
def site_ratemin_ingest(req: RateminIngestRequest, request: Request):
    auth_header = request.headers.get("authorization", "")
    token = auth_header.removeprefix("Bearer ").strip() or request.query_params.get("token", "")
    from src.platform.ratemin_service import ingest_ratemin_events, verify_ratemin_ingest_token

    if not verify_ratemin_ingest_token(token):
        raise HTTPException(401, "无效的业务系统采集器 token")
    return ingest_ratemin_events(req.events, platform=req.platform)


@app.post("/api/v1/site/ratemin/current/ingest")
def site_ratemin_current_ingest(req: RateminCurrentIngestRequest, request: Request):
    auth_header = request.headers.get("authorization", "")
    token = auth_header.removeprefix("Bearer ").strip() or request.query_params.get("token", "")
    from src.platform.ratemin_service import sync_ratemin_current_events, verify_ratemin_ingest_token

    if not verify_ratemin_ingest_token(token):
        raise HTTPException(401, "无效的业务系统采集器 token")
    return sync_ratemin_current_events(req.events, platform=req.platform, source_databases=req.source_databases)


@app.post("/api/v1/site/ratemin/users/ingest")
def site_ratemin_users_ingest(req: RateminUserIngestRequest, request: Request):
    auth_header = request.headers.get("authorization", "")
    token = auth_header.removeprefix("Bearer ").strip() or request.query_params.get("token", "")
    from src.platform.ratemin_service import ingest_ratemin_user_snapshots, verify_ratemin_ingest_token

    if not verify_ratemin_ingest_token(token):
        raise HTTPException(401, "无效的业务系统采集器 token")
    return ingest_ratemin_user_snapshots(req.users, platform=req.platform, auto_bind=req.auto_bind)


@app.get("/api/v1/admin/ratemin/status")
def admin_ratemin_status(request: Request, platform: str = "wecom"):
    require_admin_context_from_request(request)
    from src.platform.ratemin_service import list_ratemin_status

    return list_ratemin_status(platform=platform)


@app.get("/api/v1/admin/ratemin/channel-status")
def admin_ratemin_channel_status(request: Request, platform: str = "wecom"):
    require_admin_context_from_request(request)
    from src.platform.ratemin_collector_health import get_ratemin_channel_status

    return get_ratemin_channel_status(platform=platform)


@app.post("/api/v1/admin/ratemin/recover")
def admin_ratemin_recover(request: Request, platform: str = "wecom"):
    require_admin_context_from_request(request)
    from src.platform.ratemin_collector_health import recover_ratemin_channel

    return recover_ratemin_channel(platform=platform)


@app.get("/api/v1/admin/ratemin/directory")
def admin_ratemin_directory(
    request: Request,
    platform: str = "wecom",
    source_db: str = "",
    query: str = "",
    sort: str = "source_db",
    direction: str = "asc",
    limit: int = 500,
):
    require_admin_context_from_request(request)
    from src.platform.ratemin_service import list_ratemin_directory

    return {"entries": list_ratemin_directory(platform=platform, source_db=source_db, query=query, sort=sort, direction=direction, limit=limit)}


@app.get("/api/v1/admin/ratemin/bindings")
def admin_ratemin_bindings(request: Request, platform: str = "wecom", status: str = "", limit: int = 200):
    require_admin_context_from_request(request)
    from src.platform.ratemin_service import list_ratemin_bindings

    return {"bindings": list_ratemin_bindings(platform=platform, status=status, limit=limit)}


@app.post("/api/v1/admin/ratemin/auto-bind")
def admin_ratemin_auto_bind(request: Request, platform: str = "wecom", source_db: str = "", query: str = "", limit: int = 1000):
    require_admin_context_from_request(request)
    from src.platform.ratemin_service import auto_bind_all_ratemin_users

    return auto_bind_all_ratemin_users(platform=platform, source_db=source_db, query=query, limit=limit)


@app.post("/api/v1/admin/ratemin/bindings")
def admin_ratemin_bind(req: RateminBindRequest, request: Request):
    context = require_admin_context_from_request(request)
    from src.platform.ratemin_service import bind_ratemin_user

    return bind_ratemin_user(
        source_db=req.source_db,
        rate_oper_id=req.rate_oper_id,
        rate_login_name=req.rate_login_name,
        rate_display_name=req.rate_display_name,
        platform=req.platform or context["platform"],
        im_user_id=req.im_user_id,
        im_display_name=req.im_display_name,
        created_by=context["user_id"],
    )


@app.delete("/api/v1/admin/ratemin/bindings")
def admin_ratemin_unbind(request: Request, source_db: str, rate_oper_id: str, platform: str = "wecom"):
    require_admin_context_from_request(request)
    from src.platform.ratemin_service import unbind_ratemin_user

    return unbind_ratemin_user(source_db=source_db, rate_oper_id=rate_oper_id, platform=platform)


@app.get("/api/v1/admin/leave/negative-probe")
def admin_leave_negative_probe_results(request: Request, platform: str = "wecom"):
    _require_leave_manager_context(request)
    from src.platform.leave_quota_service import list_negative_probe_results

    return {"results": list_negative_probe_results(platform=platform)}


@app.post("/api/v1/admin/leave/negative-probe")
def admin_leave_negative_probe(req: LeaveNegativeProbeRequest, request: Request):
    context = _require_leave_manager_context(request)
    from src.platform.leave_quota_service import probe_negative_leave_quota

    try:
        return {
            "result": probe_negative_leave_quota(
                platform=req.platform,
                user_id=req.user_id,
                vacation_id=req.vacation_id,
                negative_duration=req.negative_duration,
                confirm_live_write=req.confirm_live_write,
                operator_user_id=context["user_id"],
            )
        }
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/v1/admin/leave/balance-target")
def admin_apply_leave_balance_target(req: LeaveBalanceTargetRequest, request: Request):
    context = _require_leave_manager_context(request)
    from src.platform.leave_quota_service import apply_leave_balance_target

    try:
        return {
            "result": apply_leave_balance_target(
                platform=req.platform,
                user_id=req.user_id,
                vacation_id=req.vacation_id,
                vacation_name=req.vacation_name,
                target_leftduration=req.target_leftduration,
                time_attr=req.time_attr,
                operator_user_id=context["user_id"],
                reason=req.reason,
                allow_local_negative=req.allow_local_negative,
            )
        }
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/v1/admin/leave/workflow-notice")
def admin_leave_workflow_notice(req: LeaveWorkflowNoticeRequest, request: Request):
    context = _require_leave_manager_context(request)
    from src.platform.leave_quota_service import (
        apply_leave_workflow_notice_update,
        plan_leave_workflow_notice_update,
        resolve_leave_workflow_template_id,
    )

    try:
        resolved = resolve_leave_workflow_template_id(template_id=req.template_id, platform="wecom")
        if not resolved.get("template_id"):
            return {
                "result": {
                    "applied": False,
                    "needs_update": False,
                    "message": "未能自动识别企微请假审批模板。请先在企微提交或找到一条请假审批记录，或手工填写请假模板 ID 后重试。",
                    "resolution": resolved,
                }
            }
        if req.apply_update:
            result = apply_leave_workflow_notice_update(
                template_id=str(resolved["template_id"]),
                notice_text=req.notice_text,
                operator_user_id=context["user_id"],
            )
        else:
            result = plan_leave_workflow_notice_update(
                template_id=str(resolved["template_id"]),
                notice_text=req.notice_text,
            )
        return {"result": {**result, "template_resolution": resolved}}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/v1/admin/leave/form-notice")
def admin_leave_form_notice(request: Request, user_id: str, platform: str = "wecom"):
    _require_leave_manager_context(request)
    from src.platform.leave_quota_service import build_employee_leave_form_notice

    try:
        return {"notice": build_employee_leave_form_notice(platform=platform, user_id=user_id)}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/v1/admin/leave/realtime-sync")
def admin_leave_realtime_status(request: Request, platform: str = "wecom"):
    _require_leave_manager_context(request)
    from src.platform.leave_quota_service import list_leave_realtime_status

    return list_leave_realtime_status(platform=platform)


@app.post("/api/v1/admin/leave/realtime-sync/run")
def admin_run_leave_realtime_sync(request: Request, platform: str = "wecom"):
    _require_leave_manager_context(request)
    from src.platform.leave_quota_service import run_realtime_leave_sync

    return run_realtime_leave_sync(platform=platform)


@app.post("/api/v1/admin/leave/policies/sync")
def admin_sync_leave_policies(request: Request, platform: str = "wecom"):
    _require_leave_manager_context(request)
    from src.platform.leave_quota_service import sync_leave_policies_from_wecom_config

    return sync_leave_policies_from_wecom_config(platform=platform)


@app.post("/api/v1/admin/leave/policies")
def admin_configure_leave_policy(req: LeavePolicyRequest, request: Request):
    context = _require_leave_manager_context(request)
    from src.platform.leave_quota_service import configure_leave_policy

    try:
        policy = configure_leave_policy(
            platform=req.platform or context["platform"],
            vacation_id=req.vacation_id,
            vacation_name=req.vacation_name,
            leave_kind=req.leave_kind,
            advance_seconds=req.advance_seconds,
            time_attr=req.time_attr,
            overtime_credit=req.overtime_credit,
        )
        return {"policy": policy}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/v1/admin/models")
def admin_model_profiles(request: Request):
    require_admin_context_from_request(request)
    from src.platform.model_management_service import list_model_profiles

    return list_model_profiles()


@app.post("/api/v1/admin/models")
def admin_save_model_profile(req: ModelProfileRequest, request: Request):
    require_admin_context_from_request(request)
    from src.platform.model_management_service import save_model_profile

    try:
        return {"profile": save_model_profile(_model_payload(req))}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/v1/admin/models/discover")
def admin_discover_models(req: ModelDiscoverRequest, request: Request):
    require_admin_context_from_request(request)
    from src.platform.model_management_service import discover_models

    return discover_models(_model_payload(req))


@app.post("/api/v1/admin/models/default")
def admin_set_default_model(req: ModelDefaultRequest, request: Request):
    require_admin_context_from_request(request)
    from src.platform.model_management_service import set_default_model_profile

    try:
        return set_default_model_profile(req.profile_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.delete("/api/v1/admin/models/{profile_id}")
def admin_delete_model_profile(profile_id: str, request: Request):
    require_admin_context_from_request(request)
    from src.platform.model_management_service import delete_model_profile

    try:
        return delete_model_profile(profile_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/v1/admin/mail/accounts")
def admin_list_mail_accounts(request: Request, platform: str = "", mail_user_id: str = ""):
    require_admin_context_from_request(request)
    from src.platform.mail_account_service import list_mail_accounts

    return list_mail_accounts(platform=platform, user_id=mail_user_id)


@app.get("/api/v1/admin/phase1/readiness")
def admin_phase1_readiness(request: Request):
    context = require_admin_context_from_request(request)
    from src.platform.phase1_readiness_service import collect_phase1_readiness

    return collect_phase1_readiness(platform=context["platform"], user_id=context["user_id"])


@app.post("/api/v1/admin/mail/accounts")
def admin_save_mail_account(req: MailAccountRequest, request: Request):
    context = require_admin_context_from_request(request)
    from src.platform.mail_account_service import save_mail_account

    try:
        payload = _model_payload(req)
        payload["user_id"] = _resolve_mail_user_id(req.platform, req.user_id, req.user_name)
        return {"account": save_mail_account(payload, updated_by=context["user_id"])}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/v1/admin/mail/accounts/infer")
def admin_infer_mail_account(req: MailAccountInferRequest, request: Request):
    require_admin_context_from_request(request)
    from src.platform.mail_account_service import infer_mail_account_defaults

    try:
        user_id = _resolve_mail_user_id(req.platform, req.user_id, req.user_name)
        return {
            "account": infer_mail_account_defaults(
                platform=req.platform,
                user_id=user_id,
                email_address=req.email_address,
            )
        }
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _resolve_mail_user_id(platform: str, user_id: str, user_name: str) -> str:
    normalized_user_id = str(user_id or "").strip()
    if normalized_user_id:
        return normalized_user_id
    name = str(user_name or "").strip()
    if not name:
        raise ValueError("请填写员工姓名；如遇同名员工，再填写企业 IM 用户 ID")
    conn = Database.get().connect()
    rows = conn.execute(
        "SELECT user_id FROM org_users WHERE platform=? AND name=? ORDER BY user_id",
        (str(platform or "wecom").strip(), name),
    ).fetchall()
    if len(rows) == 1:
        return str(rows[0][0])
    if len(rows) > 1:
        raise ValueError(f"通讯录中找到多个“{name}”，请填写企业 IM 用户 ID 后再保存")
    raise ValueError(f"未在已同步的企业 IM 通讯录中找到“{name}”。请先同步通讯录，或填写该员工的企业 IM 用户 ID")


@app.post("/api/v1/admin/mail/accounts/status")
def admin_set_mail_account_status(req: MailAccountStatusRequest, request: Request):
    context = require_admin_context_from_request(request)
    from src.platform.mail_account_service import set_mail_account_status

    try:
        kwargs = {"enabled": req.enabled, "updated_by": context["user_id"]}
        if req.account_id:
            kwargs["account_id"] = req.account_id
        return {"account": set_mail_account_status(req.platform, req.user_id, **kwargs)}
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/v1/admin/mail/accounts/test")
def admin_test_mail_account(req: MailAccountStatusRequest, request: Request):
    require_admin_context_from_request(request)
    from src.platform.mail_account_service import (
        diagnose_mail_account_connection,
        get_mail_account_by_id,
        summarize_mail_account,
        summarize_user_mailbox,
    )

    try:
        if req.account_id:
            account = get_mail_account_by_id(req.account_id)
            if not account:
                raise ValueError("未找到邮箱配置")
            user_id = str(account.get("user_id") or "")
            result = summarize_mail_account(req.account_id, limit=3)
            label = str(account.get("account_label") or "默认邮箱").strip()
            address = str(account.get("email_address") or account.get("username") or "").strip()
            account_source = f"{label} <{address}>" if address else label
        else:
            user_id = _resolve_mail_user_id(req.platform, req.user_id, req.user_name)
            result = summarize_user_mailbox(req.platform, user_id, limit=3)
            account_source = ""
        ok = _mail_test_succeeded(result)
        diagnostic = ""
        if req.account_id and not ok:
            diagnostic = diagnose_mail_account_connection(req.account_id)
            if diagnostic:
                result = f"{result}\n\n【连接诊断】\n{diagnostic}"
        return {"user_id": user_id, "account_source": account_source, "ok": ok, "result": result, "diagnostic": diagnostic}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _mail_test_succeeded(result: str) -> bool:
    failure_markers = ("尚未配置", "读取失败", "暂不支持", "需要安装", "权限不足")
    return not any(marker in str(result or "") for marker in failure_markers)


@app.delete("/api/v1/admin/mail/accounts/{platform}/{user_id}")
def admin_delete_mail_account(platform: str, user_id: str, request: Request, account_id: str = ""):
    require_admin_context_from_request(request)
    from src.platform.mail_account_service import delete_mail_account

    if account_id:
        return delete_mail_account(platform, user_id, account_id=account_id)
    return delete_mail_account(platform, user_id)


@app.post("/api/v1/admin/knowledge/import/company-guides")
def admin_import_company_guides(request: Request):
    context = require_admin_context_from_request(request)
    return import_company_guides_api(user_id=context["user_id"])


@app.get("/api/v1/admin/knowledge/entries")
def admin_knowledge_entries(request: Request, query: str = "", space_id: str = "", limit: int = 100):
    context = require_admin_context_from_request(request)
    return list_accessible_knowledge(user_id=context["user_id"], query=query, space_id=space_id, limit=limit, platform=context["platform"])


@app.get("/api/v1/admin/knowledge/permissions")
def admin_knowledge_permissions(request: Request, space_id: str = ""):
    context = require_admin_context_from_request(request)
    return knowledge_permissions(user_id=context["user_id"], space_id=space_id, platform=context["platform"])


@app.post("/api/v1/admin/org/sync")
def admin_sync_org(request: Request):
    context = require_admin_context_from_request(request)
    from src.platform.org_graph import OrgGraphService

    if context["platform"] == "wecom":
        result = OrgGraphService().sync_wecom_directory()
        return {"platform": context["platform"], "synced": True, **result}
    return {"platform": context["platform"], "synced": False, "reason": "当前平台暂未配置真实通讯录同步凭据"}


@app.post("/api/v1/admin/knowledge/collect")
def admin_collect_knowledge(req: KnowledgeCollectRequest, request: Request):
    context = require_admin_context_from_request(request)
    req.user_id = context["user_id"]
    req.platform = context["platform"]
    return collect_knowledge(req)


@app.post("/api/v1/admin/knowledge/files/upload")
def admin_upload_knowledge_file(
    request: Request,
    file: UploadFile = File(...),
    space_id: str = Form(""),
):
    context = require_admin_context_from_request(request)
    return upload_file(
        file=file,
        user_id=context["user_id"],
        space_id=space_id,
        knowledge_owner_type="auto",
        knowledge_owner_id="",
        platform=context["platform"],
    )


@app.put("/api/v1/admin/knowledge/{entry_id}")
def admin_update_knowledge(entry_id: str, req: KnowledgeUpdateRequest, request: Request):
    context = require_admin_context_from_request(request)
    req.user_id = context["user_id"]
    req.platform = context["platform"]
    return update_knowledge(entry_id, req)


@app.delete("/api/v1/admin/knowledge/{entry_id}")
def admin_delete_knowledge(entry_id: str, request: Request):
    context = require_admin_context_from_request(request)
    return delete_knowledge(entry_id, user_id=context["user_id"], platform=context["platform"])


@app.post("/api/v1/admin/knowledge/promote")
def admin_promote_knowledge(req: KnowledgePromoteRequest, request: Request):
    context = require_admin_context_from_request(request)
    req.user_id = context["user_id"]
    req.platform = context["platform"]
    return promote_knowledge(req)


@app.post("/api/v1/admin/knowledge/transfer")
def admin_transfer_knowledge(req: KnowledgeTransferRequest, request: Request):
    context = require_admin_context_from_request(request)
    req.user_id = context["user_id"]
    req.platform = context["platform"]
    return transfer_knowledge(req)


@app.get("/api/v1/user/knowledge/permissions")
def user_knowledge_permissions(request: Request, space_id: str = ""):
    context = require_user_context_from_request(request)
    return knowledge_permissions(user_id=context["user_id"], space_id=space_id, platform=context["platform"])


@app.get("/api/v1/user/entry-menu")
def user_entry_menu(request: Request):
    context = require_user_context_from_request(request)
    from src.gateway.entry_links import build_platform_entry_menu

    return build_platform_entry_menu(context["platform"], context["user_id"], is_admin=False)


@app.get("/api/v1/user/entry-payloads")
def user_entry_payloads(request: Request):
    context = require_user_context_from_request(request)
    from src.gateway.entry_links import build_platform_entry_payloads

    return build_platform_entry_payloads(context["platform"], context["user_id"], is_admin=False)


@app.get("/api/v1/user/assistant-profile")
def user_assistant_profile(request: Request):
    context = require_user_context_from_request(request)
    from src.platform.assistant_profile_service import get_assistant_profile

    return get_assistant_profile(platform=context["platform"], user_id=context["user_id"]) or {}


@app.get("/api/v1/user/subscriptions")
def user_subscriptions(request: Request):
    context = require_user_context_from_request(request)
    from src.platform.public_data_service import list_subscriptions

    return {"subscriptions": list_subscriptions(user_id=context["user_id"], platform=context["platform"])}


@app.post("/api/v1/user/subscriptions")
def user_create_subscription(req: PublicDataSubscriptionRequest, request: Request):
    context = require_user_context_from_request(request)
    from src.platform.public_data_service import create_subscription

    return create_subscription(platform=context["platform"], user_id=context["user_id"], kind=req.kind, query=req.query, schedule=req.schedule, params=req.params)


@app.patch("/api/v1/user/subscriptions/{subscription_id}")
def user_update_subscription(subscription_id: str, req: SubscriptionStatusRequest, request: Request):
    context = require_user_context_from_request(request)
    from src.platform.public_data_service import set_subscription_enabled

    try:
        return set_subscription_enabled(subscription_id, req.enabled, actor_user_id=context["user_id"])
    except (ValueError, PermissionError) as exc:
        raise HTTPException(403, str(exc))


@app.delete("/api/v1/user/subscriptions/{subscription_id}")
def user_delete_subscription(subscription_id: str, request: Request):
    context = require_user_context_from_request(request)
    from src.platform.public_data_service import delete_subscription

    try:
        return delete_subscription(subscription_id, actor_user_id=context["user_id"])
    except PermissionError as exc:
        raise HTTPException(403, str(exc))


@app.get("/api/v1/admin/public-data/sources")
def admin_public_data_sources(request: Request):
    require_admin_context_from_request(request)
    from src.platform.public_data_service import list_data_source_configs

    return {"sources": list_data_source_configs()}


@app.post("/api/v1/admin/public-data/sources")
def admin_save_public_data_source(req: PublicDataSourceRequest, request: Request):
    require_admin_context_from_request(request)
    from src.platform.public_data_service import save_data_source_config

    try:
        return {"source": save_data_source_config(_model_payload(req))}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/v1/admin/public-data/sources/test")
def admin_test_public_data_source(req: PublicDataSourceTestRequest, request: Request):
    require_admin_context_from_request(request)
    from src.platform.public_data_service import test_data_source

    return test_data_source(req.kind, query=req.query, params=req.params)


@app.delete("/api/v1/admin/public-data/sources/{kind}")
def admin_delete_public_data_source(kind: str, request: Request):
    require_admin_context_from_request(request)
    from src.platform.public_data_service import delete_data_source_config

    return delete_data_source_config(kind)


@app.get("/api/v1/admin/integrations")
def admin_integrations(request: Request):
    context = require_admin_context_from_request(request)
    from src.platform.integration_management_service import list_integrations

    return list_integrations(platform=context.get("platform", "wecom"), user_id=context.get("user_id", ""))


@app.post("/api/v1/admin/integrations/test")
def admin_test_integration(req: IntegrationTestRequest, request: Request):
    context = require_admin_context_from_request(request)
    from src.platform.integration_management_service import test_integration

    try:
        return test_integration(
            req.integration_id,
            platform=context.get("platform", "wecom"),
            user_id=context.get("user_id", ""),
            query=req.query,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/v1/admin/phase2/notification-audit")
def admin_phase2_notification_audit(request: Request, user_id: str = "", platform: str = ""):
    context = require_admin_context_from_request(request)
    normalized_platform = platform or context["platform"]
    from src.platform.daily_brief_service import list_daily_brief_deliveries
    from src.platform.public_data_service import list_subscription_audit

    conn = Database.get().connect()
    process_rows = conn.execute(
        "SELECT platform, user_id, source, item_id, action, detail, created_at FROM process_notification_audit "
        "WHERE (? = '' OR user_id = ?) AND platform = ? ORDER BY created_at DESC LIMIT 200",
        (user_id, user_id, normalized_platform),
    ).fetchall()
    return {
        "daily_briefs": list_daily_brief_deliveries(user_id=user_id, platform=normalized_platform),
        "process_notifications": [dict(row) for row in process_rows],
        "public_subscriptions": list_subscription_audit(user_id=user_id, platform=normalized_platform),
    }


@app.get("/api/v1/user/knowledge/entries")
def user_knowledge_entries(request: Request, query: str = "", space_id: str = "", limit: int = 100):
    context = require_user_context_from_request(request)
    return list_accessible_knowledge(user_id=context["user_id"], query=query, space_id=space_id, limit=limit, platform=context["platform"])


@app.post("/api/v1/user/knowledge/collect")
def user_collect_knowledge(req: KnowledgeCollectRequest, request: Request):
    context = require_user_context_from_request(request)
    req.user_id = context["user_id"]
    req.platform = context["platform"]
    return collect_knowledge(req)


@app.post("/api/v1/user/knowledge/files/upload")
def user_upload_knowledge_file(
    request: Request,
    file: UploadFile = File(...),
    space_id: str = Form(""),
):
    context = require_user_context_from_request(request)
    return upload_file(
        file=file,
        user_id=context["user_id"],
        space_id=space_id,
        knowledge_owner_type="auto",
        knowledge_owner_id="",
        platform=context["platform"],
    )


@app.put("/api/v1/user/knowledge/{entry_id}")
def user_update_knowledge(entry_id: str, req: KnowledgeUpdateRequest, request: Request):
    context = require_user_context_from_request(request)
    req.user_id = context["user_id"]
    req.platform = context["platform"]
    return update_knowledge(entry_id, req)


@app.delete("/api/v1/user/knowledge/{entry_id}")
def user_delete_knowledge(entry_id: str, request: Request):
    context = require_user_context_from_request(request)
    return delete_knowledge(entry_id, user_id=context["user_id"], platform=context["platform"])


@app.post("/api/v1/user/knowledge/promote")
def user_promote_knowledge(req: KnowledgePromoteRequest, request: Request):
    context = require_user_context_from_request(request)
    req.user_id = context["user_id"]
    req.platform = context["platform"]
    return promote_knowledge(req)


@app.post("/api/v1/user/knowledge/transfer")
def user_transfer_knowledge(req: KnowledgeTransferRequest, request: Request):
    context = require_user_context_from_request(request)
    req.user_id = context["user_id"]
    req.platform = context["platform"]
    return transfer_knowledge(req)


@app.get("/api/v1/admin/runtime/status")
def admin_runtime_status(request: Request):
    require_admin_context_from_request(request)
    from scripts.validate_external_runtime import collect_runtime_validation_report

    return {
        "health": system_health(),
        "runtime": collect_runtime_validation_report(),
    }

# ---- Spaces ----

@app.post("/api/v1/spaces")
def create_space(req: SpaceRequest):
    sr = get_space_registry()
    record = sr.register(
        space_id=req.space_id,
        name=req.name,
        space_type=req.space_type,
        description=req.description,
        members=req.members,
    )
    return {"space_id": record.space_id, "name": record.name, "type": record.space_type}

@app.get("/api/v1/spaces")
def list_spaces():
    return get_space_registry().stats()

@app.put("/api/v1/spaces/members")
def add_space_member(req: SpaceMemberRequest):
    sr = get_space_registry()
    record = sr.add_member(req.space_id, req.user_id)
    if record is None:
        raise HTTPException(404, f"Space {req.space_id} not found")
    return {"space_id": record.space_id, "members": record.members}


@app.put("/api/v1/spaces/link")
def link_space(req: SpaceLinkRequest):
    sr = get_space_registry()
    record = sr.link_spaces(req.source_space_id, req.target_space_id)
    if record is None:
        raise HTTPException(404, f"Space {req.source_space_id} not found")
    return {"space_id": record.space_id, "linked_spaces": record.metadata.get("linked_spaces", [])}


@app.get("/api/v1/spaces/{space_id}/links")
def list_space_links(space_id: str):
    return {"space_id": space_id, "linked_spaces": get_space_registry().get_linked_spaces(space_id)}

@app.delete("/api/v1/spaces/{space_id}")
def delete_space(space_id: str):
    sr = get_space_registry()
    if not sr.delete(space_id):
        raise HTTPException(404, f"Space {space_id} not found")
    return {"space_id": space_id, "deleted": True}

# ---- Knowledge ----

@app.post("/api/v1/knowledge")
def create_knowledge(req: KnowledgeCreateRequest):
    kr = get_knowledge_repo()
    try:
        ot = KnowledgeOwnerType(req.owner_type)
    except ValueError:
        raise HTTPException(400, f"Invalid owner_type: {req.owner_type}")
    entry = KnowledgeEntry(id=req.id, owner_type=ot, owner_id=req.owner_id,
                           content=req.content, tags=req.tags)
    kr.save(entry)
    return {"id": entry.id, "owner_type": entry.owner_type.value, "owner_id": entry.owner_id}

@app.get("/api/v1/knowledge/search")
def search_knowledge(query: str, user_id: str = "", space_id: str = "", limit: int = 20):
    kr = get_knowledge_repo()
    results = kr.search_accessible(query, user_id=user_id, space_id=space_id, limit=limit) if user_id else kr.search(query, limit=limit)
    return {"results": [
        _knowledge_entry_to_dict(e, user_id=user_id, space_id=space_id)
        for e in results
    ]}

@app.get("/api/v1/knowledge")
def list_knowledge(owner_type: str = "", owner_id: str = "", user_id: str = "", limit: int = 50):
    kr = get_knowledge_repo()
    if user_id:
        results = kr.list_accessible(user_id=user_id, limit=limit)
    elif owner_type and owner_id:
        try:
            ot = KnowledgeOwnerType(owner_type)
        except ValueError:
            raise HTTPException(400, f"Invalid owner_type: {owner_type}")
        results = kr.list_for_owner(ot, owner_id)
    else:
        results = kr.list_for_owner(KnowledgeOwnerType.ORGANIZATION, "*")
    return {"entries": [_knowledge_entry_to_dict(e, user_id=user_id) for e in results[:limit]]}


@app.get("/api/v1/knowledge/{entry_id}")
def get_knowledge_entry(entry_id: str, user_id: str = "", space_id: str = ""):
    kr = get_knowledge_repo()
    entry = kr.get(entry_id)
    if entry is None:
        raise HTTPException(404, f"Entry {entry_id} not found")
    return _knowledge_entry_to_dict(entry, user_id=user_id, space_id=space_id)


@app.get("/api/v1/knowledge/accessible")
def list_accessible_knowledge(user_id: str, query: str = "", space_id: str = "", limit: int = 50, platform: str = "wecom"):
    kr = get_knowledge_repo()
    if platform == "wecom":
        results = kr.search_accessible(query, user_id=user_id, space_id=space_id, limit=limit) if query else kr.list_accessible(user_id=user_id, limit=limit)
    else:
        results = _list_accessible_by_platform(kr, user_id=user_id, query=query, space_id=space_id, limit=limit, platform=platform)
    return {"entries": [_knowledge_entry_to_dict(e, user_id=user_id, space_id=space_id, platform=platform) for e in results]}


@app.get("/api/v1/knowledge/permissions")
def knowledge_permissions(user_id: str, space_id: str = "", platform: str = "wecom"):
    from src.knowledge.acl import default_write_scope, resolve_role, visible_scopes, writable_scopes
    from src.platform.org_graph import OrgGraphService

    role = resolve_role(user_id, space_id, platform=platform)
    graph = OrgGraphService()
    profile = graph.get_user_profile(platform, user_id) or {}
    write_scopes = writable_scopes(role, user_id, platform=platform)
    default_owner_type, default_owner_id = default_write_scope(role, user_id, platform=platform)
    return {
        "user_id": user_id,
        "space_id": space_id,
        "role": role.name,
        "visible_scopes": [{"owner_type": owner_type, "owner_id": owner_id} for owner_type, owner_id in visible_scopes(role, user_id, platform=platform)],
        "writable_scopes": [{"owner_type": owner_type, "owner_id": owner_id} for owner_type, owner_id in write_scopes],
        "default_write_scope": {"owner_type": default_owner_type, "owner_id": default_owner_id},
        "managed_departments": profile.get("leader_departments", []),
        "departments": profile.get("departments", []),
        "is_admin": bool(profile.get("is_admin")),
        "can_manage_organization": role.value >= 4,
        "can_manage_department": role.value >= 3,
        "can_manage_project": role.value >= 2,
        "can_manage_personal": role.value >= 1,
    }

@app.delete("/api/v1/knowledge/{entry_id}")
def delete_knowledge(entry_id: str, user_id: str = "", platform: str = "wecom"):
    from src.knowledge.acl import may_write, resolve_role

    kr = get_knowledge_repo()
    entry = kr.get(entry_id)
    if entry is None:
        raise HTTPException(404, f"Entry {entry_id} not found")
    if user_id:
        role = resolve_role(user_id, "", platform=platform)
        if not may_write(role, entry.owner_type.value, entry.owner_id, user_id, platform=platform):
            raise HTTPException(403, "Permission denied")
    if not kr.delete(entry_id, user_id=""):
        raise HTTPException(404, f"Entry {entry_id} not found")
    return {"id": entry_id, "deleted": True}


@app.put("/api/v1/knowledge/{entry_id}")
def update_knowledge(entry_id: str, req: KnowledgeUpdateRequest):
    from src.knowledge.acl import may_write, resolve_role

    kr = get_knowledge_repo()
    entry = kr.get(entry_id)
    if entry is None:
        raise HTTPException(404, f"Entry {entry_id} not found")
    role = resolve_role(req.user_id, "", platform=req.platform)
    if req.user_id and not may_write(role, entry.owner_type.value, entry.owner_id, req.user_id, platform=req.platform):
        raise HTTPException(403, "Permission denied")
    entry.content = f"{req.title}\n\n{req.content}" if req.title else req.content
    entry.tags = list(req.tags)
    if req.title:
        entry.metadata["title"] = req.title
    kr.save(entry)
    return _knowledge_entry_to_dict(entry)


@app.post("/api/v1/knowledge/promote")
def promote_knowledge(req: KnowledgePromoteRequest):
    from src.knowledge.acl import may_write, resolve_role
    from src.knowledge.service import KnowledgeService

    kr = get_knowledge_repo()
    entry = kr.get(req.entry_id)
    if entry is None:
        raise HTTPException(404, f"Entry {req.entry_id} not found")
    role = resolve_role(req.user_id, "", platform=req.platform)
    if req.user_id and not may_write(role, entry.owner_type.value, entry.owner_id, req.user_id, platform=req.platform):
        raise HTTPException(403, "Permission denied")
    if not req.target_owner_type or req.target_owner_type == "auto" or not req.target_owner_id:
        req.target_owner_type, req.target_owner_id = _resolve_auto_knowledge_owner(req.user_id, "", platform=req.platform)
    try:
        target_owner_type = KnowledgeOwnerType(req.target_owner_type)
    except ValueError:
        raise HTTPException(400, f"Invalid target_owner_type: {req.target_owner_type}")
    if req.user_id and not may_write(role, target_owner_type.value, req.target_owner_id, req.user_id, platform=req.platform):
        raise HTTPException(403, "Permission denied")
    service = KnowledgeService(kr)
    new_entry_id = req.new_entry_id or f"{req.entry_id}-promoted-{target_owner_type.value}"
    promoted = service.promote_entry(
        entry,
        target_owner_type=target_owner_type,
        target_owner_id=req.target_owner_id,
        new_entry_id=new_entry_id,
        extra_tags=["promoted"],
    )
    return _knowledge_entry_to_dict(promoted)


@app.post("/api/v1/knowledge/transfer")
def transfer_knowledge(req: KnowledgeTransferRequest):
    from src.knowledge.acl import may_read, may_write, resolve_role

    action = (req.action or "copy").strip().lower()
    if action not in {"copy", "cut"}:
        raise HTTPException(400, "action must be copy or cut")
    kr = get_knowledge_repo()
    entry = kr.get(req.entry_id)
    if entry is None:
        raise HTTPException(404, f"Entry {req.entry_id} not found")
    role = resolve_role(req.user_id, "", platform=req.platform)
    if req.user_id and not may_read(role, entry.owner_type.value, entry.owner_id, req.user_id, platform=req.platform):
        raise HTTPException(403, "Permission denied")
    if action == "cut" and req.user_id and not may_write(role, entry.owner_type.value, entry.owner_id, req.user_id, platform=req.platform):
        raise HTTPException(403, "Permission denied")
    if not req.target_owner_type or req.target_owner_type == "auto" or not req.target_owner_id:
        req.target_owner_type, req.target_owner_id = _resolve_auto_knowledge_owner(req.user_id, "", platform=req.platform)
    try:
        target_owner_type = KnowledgeOwnerType(req.target_owner_type)
    except ValueError:
        raise HTTPException(400, f"Invalid target_owner_type: {req.target_owner_type}")
    if req.user_id and not may_write(role, target_owner_type.value, req.target_owner_id, req.user_id, platform=req.platform):
        raise HTTPException(403, "Permission denied")

    new_entry_id = req.new_entry_id or _build_transferred_knowledge_id(entry.id, target_owner_type.value, req.target_owner_id, action)
    transfer_marker = "copied_from" if action == "copy" else "moved_from"
    transferred = KnowledgeEntry(
        id=new_entry_id,
        owner_type=target_owner_type,
        owner_id=req.target_owner_id,
        content=entry.content,
        tags=list(dict.fromkeys([*entry.tags, action])),
        metadata={
            **entry.metadata,
            transfer_marker: entry.id,
            "transfer_action": action,
            "transferred_by": req.user_id,
            "transferred_at": time.time(),
        },
        read_roles=list(entry.read_roles),
        write_roles=list(entry.write_roles),
    )
    kr.save(transferred)
    source_deleted = False
    if action == "cut":
        source_deleted = bool(kr.delete(entry.id, user_id=req.user_id))
        if not source_deleted:
            raise HTTPException(500, "Target entry was created but source entry could not be removed")
    return {
        "action": action,
        "source_entry_id": entry.id,
        "source_deleted": source_deleted,
        "entry": _knowledge_entry_to_dict(transferred, user_id=req.user_id, platform=req.platform),
    }


def _build_transferred_knowledge_id(source_id: str, target_owner_type: str, target_owner_id: str, action: str) -> str:
    safe_target = re.sub(r"[^0-9A-Za-z_-]+", "-", f"{target_owner_type}-{target_owner_id}").strip("-") or target_owner_type
    return f"{source_id}-{action}-{safe_target}-{int(time.time() * 1000)}"


@app.post("/api/v1/knowledge/import/company-guides")
def import_company_guides_api(user_id: str = ""):
    from src.knowledge.acl import resolve_role
    from src.knowledge.company_guides import import_company_guides

    if not user_id:
        raise HTTPException(400, "Provide user_id")
    role = resolve_role(user_id, "")
    if role.value < 4:
        raise HTTPException(403, "Permission denied")
    entries = import_company_guides(get_knowledge_repo())
    return {"imported": len(entries), "entries": [_knowledge_entry_to_dict(e, user_id=user_id) for e in entries]}

@app.post("/api/v1/knowledge/collect")
def collect_knowledge(req: KnowledgeCollectRequest):
    if req.user_id and (not req.owner_type or req.owner_type == "auto" or not req.owner_id):
        req.owner_type, req.owner_id = _resolve_auto_knowledge_owner(req.user_id, req.space_id, platform=req.platform)
    if req.user_id:
        from src.knowledge.acl import may_write, resolve_role

        role = resolve_role(req.user_id, req.space_id, platform=req.platform)
        if not may_write(role, req.owner_type, req.owner_id, req.user_id, platform=req.platform):
            raise HTTPException(403, "Permission denied")
    kr = get_knowledge_repo()
    collector = KnowledgeCollector(kr)
    if req.url:
        entry = collector.collect_url(req.url, owner_type=req.owner_type, owner_id=req.owner_id, tags=req.tags)
        if entry is None:
            raise HTTPException(400, f"Failed to collect URL: {req.url}")
        return {"id": entry.id, "source": "url", "owner_type": entry.owner_type.value}
    if req.text:
        entry = collector.collect_text(req.text, req.title or "untitled", owner_type=req.owner_type, owner_id=req.owner_id, tags=req.tags)
        return {"id": entry.id, "source": "text", "owner_type": entry.owner_type.value}
    raise HTTPException(400, "Provide url= or text=")


def _resolve_auto_knowledge_owner(user_id: str, space_id: str = "", platform: str = "wecom") -> tuple[str, str]:
    from src.knowledge.acl import default_write_scope, resolve_role

    role = resolve_role(user_id, space_id, platform=platform)
    return default_write_scope(role, user_id, platform=platform)

# ---- Host Agent ----

class HostSummarizeRequest(BaseModel):
    space_id: str
    limit: int = 50

class SetDeadlineRequest(BaseModel):
    task_id: str
    due_at: str

class SetPriorityRequest(BaseModel):
    task_id: str
    priority: str

class CreateTaskRequest(BaseModel):
    title: str
    description: str = ""
    project_id: str
    assignee_user_id: str | None = None
    priority: str = "medium"

@app.post("/api/v1/tasks")
def create_task(req: CreateTaskRequest):
    r = get_repo()
    task = r.create_task(
        title=req.title, description=req.description,
        project_id=req.project_id, assignee_user_id=req.assignee_user_id, priority=req.priority,
    )
    return {"task_id": task.id, "title": task.title, "status": task.status.value, "priority": task.priority}

# ---- Analytics ----

@app.get("/api/v1/analytics")
def get_analytics(space_id: str = ""):
    from src.orchestrator.task_analytics import TaskAnalytics
    r = get_repo()
    ta = TaskAnalytics(r)
    return ta.dashboard_summary() if not space_id else ta.project_stats(space_id=space_id)

# ---- Batch Operations ----

class BatchTransitionRequest(BaseModel):
    task_ids: list[str]
    status: str

@app.put("/api/v1/tasks/batch")
def batch_transition(req: BatchTransitionRequest):
    try:
        status = TaskStatus(req.status)
    except ValueError:
        raise HTTPException(400, f"Invalid status: {req.status}")
    r = get_repo()
    results = []
    for tid in req.task_ids:
        r.update_task_status(tid, status)
        results.append({"task_id": tid, "status": status.value})
    return {"count": len(results), "results": results}

@app.get("/api/v1/tasks/export")
def export_tasks(space_id: str = "", format: str = "json"):
    r = get_repo()
    tasks = r.list_tasks(project_id=space_id)
    data = [_task_to_dict(t) for t in tasks]
    if format == "csv":
        output = io.StringIO()
        if data:
            writer = csv.DictWriter(output, fieldnames=data[0].keys())
            writer.writeheader()
            writer.writerows(data)
        return Response(content=output.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": "attachment; filename=tasks.csv"})
    return {"space_id": space_id or "all", "count": len(data), "tasks": data}

@app.put("/api/v1/priority")
def set_priority(req: SetPriorityRequest):
    if req.priority not in ("high", "medium", "low"):
        raise HTTPException(400, "Priority must be high/medium/low")
    r = get_repo()
    r.set_priority(req.task_id, req.priority)
    return {"task_id": req.task_id, "priority": req.priority}

@app.put("/api/v1/tasks/{task_id}/revert")
def revert_task(task_id: str):
    r = get_repo()
    r.revert_to_draft(task_id)
    return {"task_id": task_id, "status": "reverted"}

@app.post("/api/v1/host/summarize")
def host_summarize(req: HostSummarizeRequest):
    from src.engine.factory import build_engine
    from src.agents.host_agent import HostAgent
    r = get_repo()
    msgs = r.list_messages(space_id=req.space_id, limit=req.limit)
    if not msgs:
        raise HTTPException(404, f"No messages in space {req.space_id}")
    engine = build_engine("project")
    host = HostAgent(engine, repo=r)
    summary = host.summarize(msgs)
    actions = host.extract_actions(msgs)
    return {"space_id": req.space_id, "summary": summary, "actions": actions, "message_count": len(msgs)}

@app.post("/api/v1/host/auto-draft")
def host_auto_draft(req: HostSummarizeRequest):
    from src.engine.factory import build_engine
    from src.agents.host_agent import HostAgent
    r = get_repo()
    msgs = r.list_messages(space_id=req.space_id, limit=req.limit)
    if not msgs:
        raise HTTPException(404, f"No messages in space {req.space_id}")
    engine = build_engine("project")
    host = HostAgent(engine, repo=r)
    count = host.auto_create_drafts(req.space_id, msgs)
    return {"space_id": req.space_id, "drafts_created": count}

# ---- Work Journal ----

@app.get("/api/v1/journal/{user_id}")
def get_user_journal(user_id: str):
    from src.agents.work_journal import WorkJournal
    r = get_repo()
    journal = WorkJournal(r)
    return journal.get_summary(user_id)

# ---- Org Sync ----

@app.post("/api/v1/org/sync")
def sync_organization():
    from src.orchestrator.org_sync import OrgSynchronizer
    from src.platform.org_graph import OrgGraphService

    graph_result = OrgGraphService().sync_wecom_directory()
    compatibility_result: dict[str, Any] = {}
    compatibility_ok = True
    try:
        syncer = OrgSynchronizer(space_registry=get_space_registry(), memory_dir="./data/memory")
        compatibility_result = syncer.sync_all(sync_graph=False)
        compatibility_ok = "error" not in compatibility_result
    except Exception as exc:
        compatibility_ok = False
        compatibility_result = {"error": str(exc)}
        logger.warning("legacy organization compatibility sync failed", exc_info=True)
    return {
        "platform": "wecom",
        "synced": True,
        "graph": graph_result,
        "compatibility_ok": compatibility_ok,
        "compatibility": compatibility_result,
    }

# ---- Deadline ----

@app.put("/api/v1/deadline")
def set_deadline(req: SetDeadlineRequest):
    from src.orchestrator.deadline_tracker import DeadlineTracker
    r = get_repo()
    tracker = DeadlineTracker(r)
    ok = tracker.set_deadline(req.task_id, req.due_at)
    if not ok:
        raise HTTPException(400, "Failed to set deadline")
    return {"task_id": req.task_id, "due_at": req.due_at}

@app.post("/api/v1/deadline/check")
def check_deadlines(space_id: str = ""):
    from src.orchestrator.deadline_tracker import DeadlineTracker
    r = get_repo()
    tracker = DeadlineTracker(r)
    reminders = tracker.check_and_remind(space_id=space_id)
    return {"reminders_generated": len(reminders), "reminders": reminders}


# ---- File API ----

@app.post("/api/v1/files")
def upload_file(
    file: UploadFile = File(...),
    user_id: str = Form(...),
    space_id: str = Form(...),
    knowledge_owner_type: str = Form("auto"),
    knowledge_owner_id: str = Form(""),
    platform: str = Form("wecom"),
):
    normalized_platform = platform if isinstance(platform, str) else "wecom"
    content = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File exceeds the {MAX_UPLOAD_BYTES}-byte upload limit")
    store = _get_file_store()
    storage_space_id = space_id.strip() or "_global"
    rel_path = store.write(user_id, storage_space_id, file.filename or "unnamed", content)
    owner_type, owner_id = _resolve_knowledge_owner(
        knowledge_owner_type=knowledge_owner_type,
        knowledge_owner_id=knowledge_owner_id,
        user_id=user_id,
        space_id=space_id,
        platform=normalized_platform,
    )
    from src.knowledge.acl import may_write, resolve_role

    role = resolve_role(user_id, space_id, platform=normalized_platform)
    if not may_write(role, owner_type, owner_id, user_id, platform=normalized_platform):
        raise HTTPException(403, "Permission denied")
    # Auto-index document into knowledge base
    try:
        fpath = os.path.join(store._base, rel_path)
        collector = KnowledgeCollector(build_knowledge_repository())
        entry = collector.collect_file(fpath, owner_type=owner_type, owner_id=owner_id)
        indexed = entry.id if entry else None
        tags = list(entry.tags) if entry and getattr(entry, "tags", None) else []
        preview = (entry.content or "")[:300] if entry and getattr(entry, "content", None) else ""
    except Exception as e:
        logger.warning("File index failed: %s", e)
        indexed = None
        tags = []
        preview = ""
    return {
        "path": rel_path,
        "filename": file.filename,
        "size": len(content),
        "indexed": indexed,
        "owner_type": owner_type,
        "owner_id": owner_id,
        "tags": tags,
        "content_preview": preview,
    }


@app.get("/api/v1/files")
def list_files(space_id: str, user_id: str = ""):
    store = _get_file_store()
    if user_id:
        files = store.list_user_files(user_id, space_id)
    else:
        files = store.list_files(space_id)
    return {"files": files}


@app.delete("/api/v1/files")
def delete_file(req: FileDeleteRequest):
    store = _get_file_store()
    deleted = store.delete(req.user_id, req.space_id, req.filename)
    if not deleted:
        raise HTTPException(404, f"File not found: {req.filename!r}")
    return {"deleted": True, "filename": req.filename}


# ---- Cron API ----

@app.get("/api/v1/cron/jobs")
def list_cron_jobs():
    from src.orchestrator.cron_job import get_registry
    reg = get_registry()
    return {"jobs": [asdict(j) for j in reg.list()]}


@app.post("/api/v1/cron/jobs")
async def create_cron_job(req: Request):
    from src.orchestrator.cron_job import CronJob, get_registry
    import time
    body = await req.json()
    job = CronJob(
        id=body.get("id", f"cron-{int(time.time())}"),
        name=body.get("name", "unnamed"),
        schedule=body.get("schedule", "every 1h"),
        command=body.get("command", ""),
        no_agent=body.get("no_agent", True),
        tags=body.get("tags", []),
    )
    reg = get_registry()
    reg.register(job)
    return {"registered": job.id}


@app.delete("/api/v1/cron/jobs/{job_id}")
def delete_cron_job(job_id: str):
    from src.orchestrator.cron_job import get_registry
    reg = get_registry()
    if reg.unregister(job_id):
        return {"deleted": job_id}
    raise HTTPException(404, f"Job not found: {job_id}")


@app.post("/api/v1/cron/jobs/{job_id}/run")
def run_cron_job_now(job_id: str):
    from src.orchestrator.cron_job import cron_result_status, get_registry, run_no_agent
    reg = get_registry()
    job = reg.get(job_id)
    if not job:
        raise HTTPException(404, f"Job not found: {job_id}")
    result = run_no_agent(job.command) if job.no_agent else "REJECTED: agent mode cron execution is not implemented"
    reg.record_run(job.id, cron_result_status(result))
    return {"job_id": job_id, "result": result[:500]}


# ---- helpers ----

def _task_to_dict(t: Task) -> dict[str, Any]:
    d = asdict(t)
    d["status"] = t.status.value
    d["due_at"] = t.due_at.isoformat() if t.due_at else None
    d["blocked_by_task_id"] = t.blocked_by_task_id
    d["priority"] = t.priority
    return d


def _resolve_knowledge_owner(
    *,
    knowledge_owner_type: Any,
    knowledge_owner_id: Any,
    user_id: str,
    space_id: str,
    platform: str = "wecom",
) -> tuple[str, str]:
    raw_type = knowledge_owner_type if isinstance(knowledge_owner_type, str) else "auto"
    raw_id = knowledge_owner_id if isinstance(knowledge_owner_id, str) else ""
    normalized_type = (raw_type or "project").strip().lower()
    if normalized_type == "auto":
        return _resolve_auto_knowledge_owner(user_id, space_id, platform=platform)
    valid_types = {
        KnowledgeOwnerType.PERSONAL.value,
        KnowledgeOwnerType.PROJECT.value,
        KnowledgeOwnerType.DEPARTMENT.value,
        KnowledgeOwnerType.ORGANIZATION.value,
    }
    if normalized_type not in valid_types:
        raise HTTPException(400, f"Invalid knowledge_owner_type: {knowledge_owner_type}")

    normalized_id = (raw_id or "").strip()
    if normalized_type == KnowledgeOwnerType.PERSONAL.value:
        return normalized_type, normalized_id or user_id
    if normalized_type == KnowledgeOwnerType.ORGANIZATION.value:
        return normalized_type, "*"
    if normalized_type in {KnowledgeOwnerType.PROJECT.value, KnowledgeOwnerType.DEPARTMENT.value}:
        return normalized_type, normalized_id or space_id
    return normalized_type, normalized_id or space_id


# ---- Root ----

@app.get("/")
def root():
    return {"name": "Ant Colony API", "version": "0.3.0", "docs": "/docs"}


@app.get("/knowledge/manage", response_class=HTMLResponse)
def knowledge_management_page():
    return HTMLResponse(
        """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>知识库管理</title>
  <style>
    :root {
      --accent:#0078d4; --accent-hover:#106ebe; --accent-light:#e8f4fd;
      --surface:#faf9f8; --card:#ffffff; --card-hover:#f5f5f5;
      --border:#e0e0e0; --border-focus:#0078d4;
      --text:#1a1a1a; --text-secondary:#616161; --text-tertiary:#8a8a8a;
      --error:#c42b1c; --success:#0f7b0f; --warning:#9d5d00;
      --radius:8px; --radius-sm:4px;
      --shadow:0 2px 4px rgba(0,0,0,.04),0 1px 2px rgba(0,0,0,.06);
      --shadow-hover:0 4px 8px rgba(0,0,0,.06),0 2px 4px rgba(0,0,0,.08);
    }
    * { box-sizing:border-box; margin:0; padding:0; }
    body { background:var(--surface); color:var(--text); font-family:"Segoe UI Variable","Segoe UI",system-ui,-apple-system,sans-serif; font-size:14px; line-height:1.5; }
    header { padding:20px 32px; background:linear-gradient(180deg,rgba(255,255,255,.95),rgba(250,249,248,.85)); backdrop-filter:blur(12px); -webkit-backdrop-filter:blur(12px); border-bottom:1px solid var(--border); display:flex; gap:16px; justify-content:space-between; align-items:center; position:sticky; top:0; z-index:10; }
    h1 { font-size:24px; font-weight:600; letter-spacing:-.02em; }
    h2 { font-size:18px; font-weight:600; margin-bottom:12px; }
    h3 { font-size:15px; font-weight:600; margin-bottom:8px; }
    p { color:var(--text-secondary); margin-bottom:12px; font-size:13px; }
    main { padding:24px 32px; display:grid; grid-template-columns:340px 1fr; gap:20px; }
    .card { background:var(--card); border:1px solid var(--border); border-radius:var(--radius); padding:20px; box-shadow:var(--shadow); transition:box-shadow .15s; }
    .card:hover { box-shadow:var(--shadow-hover); }
    .stack { display:grid; gap:16px; }
    .grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; }
    label { display:block; color:var(--text-secondary); font-size:12px; font-weight:500; margin:10px 0 4px; }
    input, textarea, select { width:100%; border:1px solid var(--border); border-radius:var(--radius-sm); padding:8px 10px; background:var(--card); color:var(--text); font:inherit; font-size:13px; transition:border-color .15s,box-shadow .15s; outline:none; }
    input:focus, textarea:focus, select:focus { border-color:var(--border-focus); box-shadow:0 0 0 3px rgba(0,120,212,.15); }
    textarea { min-height:180px; resize:vertical; }
    button { border:1px solid transparent; border-radius:var(--radius-sm); padding:7px 16px; background:var(--accent); color:#fff; font:inherit; font-size:13px; font-weight:500; cursor:pointer; transition:background .15s,box-shadow .15s; }
    button:hover { background:var(--accent-hover); }
    button:active { background:#005a9e; }
    button.secondary { background:var(--card); color:var(--text); border-color:var(--border); }
    button.secondary:hover { background:var(--card-hover); }
    button.tonal { background:var(--accent-light); color:var(--accent); }
    button.tonal:hover { background:#d0e8f9; }
    button.danger { background:var(--error); color:#fff; }
    button.danger:hover { background:#a3261a; }
    button:disabled { opacity:.45; cursor:not-allowed; }
    .actions { display:flex; gap:8px; flex-wrap:wrap; margin-top:12px; }
    .chip { display:inline-flex; align-items:center; border-radius:var(--radius-sm); padding:3px 8px; background:#f3f3f3; color:var(--text-secondary); margin:0 4px 4px 0; font-size:12px; }
    .chip.ok { color:var(--success); background:#e8f5e9; }
    .chip.bad { color:var(--error); background:#fde7e9; }
    .list { display:grid; gap:8px; max-height:560px; overflow:auto; }
    .scope-tree { display:grid; gap:6px; }
    .scope-node { border:1px solid var(--border); border-radius:var(--radius-sm); padding:10px 12px; background:var(--card); cursor:pointer; transition:background .12s,border-color .12s; }
    .scope-node:hover { background:var(--accent-light); border-color:var(--accent); }
    .scope-node.active-scope { border-color:var(--accent); background:#eff6fc; }
    .scope-node strong { display:block; margin-bottom:2px; font-size:13px; }
    .scope-node.readonly { background:#fafafa; }
    .item { border:1px solid var(--border); border-radius:var(--radius-sm); padding:12px; background:var(--card); cursor:pointer; transition:border-color .12s,box-shadow .12s; }
    .item:hover { border-color:var(--accent); box-shadow:0 1px 3px rgba(0,0,0,.06); }
    .item.active { border-color:var(--accent); background:#f0f6fc; }
    .meta { color:var(--text-tertiary); font-size:12px; margin-top:4px; }
    table { width:100%; border-collapse:collapse; font-size:13px; }
    th { padding:10px; border-bottom:2px solid var(--border); text-align:left; font-weight:600; color:var(--text-secondary); font-size:12px; white-space:nowrap; }
    td { padding:10px; border-bottom:1px solid var(--border); vertical-align:top; }
    tr:hover td { background:#fafafa; }
    .status { min-height:20px; color:var(--text-secondary); font-size:12px; }
    .muted { color:var(--text-tertiary) !important; font-size:12px; }
    @media (max-width: 960px) { header, main, .grid { display:block; } main { padding:0 16px 24px; } .card { margin-bottom:16px; } }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>知识库管理</h1>
      <p>按企业 IM 组织权限自动适配可见范围、可写范围和管理动作。</p>
    </div>
    <div id="identity" class="chip">等待识别</div>
  </header>
  <main>
    <aside class="stack">
      <div class="card">
        <h2>筛选</h2>
        <label>用户 ID</label><input id="userId" placeholder="企业 IM user_id">
        <label>关键词</label><input id="query" placeholder="标题、制度名、关键词">
        <label>空间 ID</label><input id="spaceId" placeholder="项目或部门空间，可留空">
        <div class="actions">
          <button onclick="loadEntries()">查询知识</button>
          <button class="secondary" onclick="loadPermissions()">刷新权限</button>
          <button class="tonal" onclick="syncOrg()">同步组织架构</button>
        </div>
        <div id="perm" class="status"></div>
      </div>
      <div class="card">
        <h2>组织目录</h2>
        <p>按当前用户可见范围和可写范围分组显示，员工只能看到自己有权访问的知识库目录。</p>
        <div id="scopeTree" class="scope-tree">等待权限识别</div>
      </div>
      <div class="card">
        <h2>新增知识</h2>
        <label>标题</label><input id="newTitle" placeholder="例如：车间通行管理规定">
        <label>入库范围</label>
        <select id="newOwnerType">
          <option value="auto">自动（系统选择）</option>
        </select>
        <div id="autoOwner" class="status">等待权限识别</div>
        <label>标签</label><input id="newTags" placeholder="逗号分隔">
        <label>正文</label><textarea id="newContent" placeholder="粘贴要入库的内容"></textarea>
        <button onclick="createEntry()">新增到知识库</button>
      </div>
      <div class="card">
        <h2>上传文档入库</h2>
        <p>支持批量选择文件，系统会解析文档内容并自动提取关键字和摘要。</p>
        <label>目标入库范围</label>
        <select id="uploadOwnerType">
          <option value="auto">自动（系统选择）</option>
        </select>
        <input id="knowledgeFile" type="file" accept=".txt,.md,.docx,.pdf,.xlsx,.pptx,.csv,.json" multiple>
        <button onclick="uploadKnowledgeFiles()">上传并索引</button>
        <div id="uploadStatus" class="status"></div>
        <div id="uploadResults" class="list" style="margin-top:12px"></div>
      </div>
    </aside>
    <section class="stack">
      <div class="card">
        <div class="actions">
        <button class="secondary" onclick="importGuides()">导入公司级说明书文档</button>
          <button class="tonal" onclick="openSelected()">打开选中条目</button>
        </div>
        <div id="guideStatus" class="status"></div>
      </div>
      <div class="grid">
        <div class="card">
          <h2>知识条目</h2>
          <div class="actions"><button class="tonal" onclick="clearScopeFilter()">清除筛选</button></div>
          <div id="scopeFilter" class="status"></div>
          <div id="result" class="list"></div>
        </div>
        <div class="card">
          <h2>编辑选中条目</h2>
          <label>条目 ID</label><input id="entryId" readonly>
          <label>标题</label><input id="title">
          <label>标签</label><input id="tags">
          <label>内容</label><textarea id="editor"></textarea>
          <div class="actions">
            <button id="saveBtn" onclick="updateEntry()" disabled>保存</button>
            <button id="deleteBtn" class="danger" onclick="deleteEntry()" disabled>删除</button>
          </div>
          <h3>自动升级/复制</h3>
          <p>系统会按当前用户权限自动选择最高可写范围，不需要手动填写目标范围。</p>
          <button class="secondary" onclick="promoteEntry()">自动升级知识条目</button>
          <h3>知识条目迁移</h3>
          <p>选择有写入权限的目标知识库后，可将当前条目拷贝或剪切到目标组织库。</p>
          <label>目标知识库</label>
          <select id="transferTarget"><option value="">等待权限识别</option></select>
          <div class="actions">
            <button class="secondary" onclick="transferEntry('copy')">拷贝到目标库</button>
            <button class="danger" onclick="transferEntry('cut')">剪切到目标库</button>
          </div>
          <div id="editStatus" class="status"></div>
        </div>
      </div>
    </section>
  </main>
  <script>
    (function () {
      function query(name) {
        var match = new RegExp('[?&]' + name + '=([^&]*)').exec(window.location.search);
        return match ? decodeURIComponent(match[1].replace(/\\+/g, ' ')) : '';
      }
      var platform = query('platform') || 'wecom';
      var userId = query('user_id');
      var token = query('admin_token');
      if (!userId || !token || !window.XMLHttpRequest) return;
      var xhr = new XMLHttpRequest();
      xhr.open('GET', '/api/v1/admin/profile?platform=' + encodeURIComponent(platform) + '&user_id=' + encodeURIComponent(userId) + '&admin_token=' + encodeURIComponent(token), true);
      xhr.onreadystatechange = function () {
        if (xhr.readyState !== 4) return;
        var identity = document.getElementById('identity');
        var profileBox = document.getElementById('profileBox');
        if (!identity || !profileBox) return;
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            var profile = JSON.parse(xhr.responseText || '{}');
            identity.textContent = (profile.platform || platform) + ' / ' + (profile.user_id || userId) + ' / ' + (profile.role || 'admin');
            profileBox.textContent = '用户：' + (profile.user_id || userId) + ' / 角色：' + (profile.role || 'admin');
          } catch (err) {
            identity.textContent = '已验证';
            profileBox.textContent = '管理员身份已验证';
          }
        } else {
          identity.textContent = '验证失败';
          profileBox.textContent = '验证失败，请从 Bot 重新打开管理员控制台';
        }
      };
      xhr.send();
    })();
  </script>
  <script>
    (function () {
      function query(name) {
        var match = new RegExp('[?&]' + name + '=([^&]*)').exec(window.location.search);
        return match ? decodeURIComponent(match[1].replace(/\\+/g, ' ')) : '';
      }
      var platform = query('platform') || 'wecom';
      var userId = query('user_id');
      var token = query('admin_token');
      if (!userId || !token || !window.XMLHttpRequest) return;
      var xhr = new XMLHttpRequest();
      xhr.open('GET', '/api/v1/admin/profile?platform=' + encodeURIComponent(platform) + '&user_id=' + encodeURIComponent(userId) + '&admin_token=' + encodeURIComponent(token), true);
      xhr.onreadystatechange = function () {
        if (xhr.readyState !== 4) return;
        var identity = document.getElementById('identity');
        var profileBox = document.getElementById('profileBox');
        if (!identity || !profileBox) return;
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            var profile = JSON.parse(xhr.responseText || '{}');
            identity.textContent = (profile.platform || platform) + ' / ' + (profile.user_id || userId) + ' / ' + (profile.role || 'admin');
            profileBox.textContent = '用户：' + (profile.user_id || userId) + ' / 角色：' + (profile.role || 'admin');
          } catch (err) {
            identity.textContent = '已验证';
            profileBox.textContent = '管理员身份已验证';
          }
        } else {
          identity.textContent = '验证失败';
          profileBox.textContent = '验证失败，请从 Bot 重新打开管理员控制台';
        }
      };
      xhr.send();
    })();
  </script>
  <script>
    (function () {
      function getParam(name) {
        var match = new RegExp('[?&]' + name + '=([^&]*)').exec(window.location.search || '');
        return match ? decodeURIComponent(match[1].replace(/\\+/g, ' ')) : '';
      }
      var platform = getParam('platform') || 'wecom';
      var userId = getParam('user_id');
      var token = getParam('admin_token');
      if (!userId || !token || !window.XMLHttpRequest) return;
      var xhr = new XMLHttpRequest();
      xhr.open('GET', '/api/v1/admin/profile?platform=' + encodeURIComponent(platform) + '&user_id=' + encodeURIComponent(userId) + '&admin_token=' + encodeURIComponent(token), true);
      xhr.onreadystatechange = function () {
        if (xhr.readyState !== 4) return;
        var identity = document.getElementById('identity');
        var profileBox = document.getElementById('profileBox');
        if (!identity || !profileBox) return;
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            var profile = JSON.parse(xhr.responseText || '{}');
            identity.textContent = (profile.platform || platform) + ' / ' + (profile.user_id || userId) + ' / ' + (profile.role || 'admin');
            profileBox.textContent = '用户：' + (profile.user_id || userId) + ' / 角色：' + (profile.role || 'admin');
          } catch (e) {
            identity.textContent = '已验证';
            profileBox.textContent = '管理员身份已通过验证';
          }
        } else {
          identity.textContent = '验证失败';
          profileBox.textContent = '验证失败，请从 Bot 重新打开管理员控制台';
        }
      };
      xhr.send(null);
    })();
  </script>
  <script>
    const params = new URLSearchParams(location.search);
    const hasAdminToken = !!params.get('admin_token');
    const hasUserToken = !!params.get('user_token');
    const adminQuery = () => `platform=${encodeURIComponent(params.get('platform') || 'wecom')}&user_id=${encodeURIComponent(params.get('user_id') || '')}&admin_token=${encodeURIComponent(params.get('admin_token') || '')}`;
    const userQuery = () => `platform=${encodeURIComponent(params.get('platform') || 'wecom')}&user_id=${encodeURIComponent(params.get('user_id') || userId())}&user_token=${encodeURIComponent(params.get('user_token') || '')}`;
    function userId() { return document.getElementById('userId').value.trim() || params.get('user_id') || ''; }
    function val(id) { const el = document.getElementById(id); return el ? el.value.trim() : ''; }
    function safe(value) {
      return String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
    }
    function jsString(value) { return JSON.stringify(String(value ?? '')); }
    function jsAttr(value) { return safe(jsString(value)); }
    function setStatus(id, text, bad=false) { const el = document.getElementById(id); el.textContent = text; el.style.color = bad ? 'var(--error)' : 'var(--text-secondary)'; }
    function scopeLabel(scope) {
      const labels = {organization:'公司', department:'部门', project:'项目', personal:'个人'};
      const label = labels[scope.owner_type] || scope.owner_type;
      const id = scope.owner_id === '*' ? '全公司' : scope.owner_id || '';
      return id ? `${label} / ${id}` : label;
    }
    function scopeValue(scope) { return `${scope.owner_type}:${scope.owner_id}`; }
    async function requestJson(url, options = {}) {
      const resp = await fetch(url, options);
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || data.error || JSON.stringify(data));
      return data;
    }
    function adminUrl(path) { return `${path}${path.includes('?') ? '&' : '?'}${adminQuery()}`; }
    function userUrl(path) { return `${path}${path.includes('?') ? '&' : '?'}${userQuery()}`; }
    function knowledgeUrl(adminPath, userPath, fallbackPath) {
      if (hasAdminToken) return adminUrl(adminPath);
      if (hasUserToken) return userUrl(userPath);
      return fallbackPath;
    }
    function renderScopeGroups(perm, entries = []) {
      const root = document.getElementById('scopeTree');
      const writable = new Set((perm.writable_scopes || []).map(scope => `${scope.owner_type}:${scope.owner_id}`));
      const counts = {};
      for (const item of entries) {
        const key = `${item.owner_type}:${item.owner_id}`;
        counts[key] = (counts[key] || 0) + 1;
      }
      const visible = perm.visible_scopes || [];
      if (!visible.length) {
        root.textContent = '暂无可见知识库目录';
        return;
      }
      root.innerHTML = visible.map(scope => {
        const key = `${scope.owner_type}:${scope.owner_id}`;
        const canWrite = writable.has(key);
        return `<div class="scope-node ${canWrite ? '' : 'readonly'}" data-scope-key="${safe(key)}" onclick="filterByScope(${jsAttr(key)})" style="cursor:pointer">
          <strong>${safe(scopeLabel(scope))}</strong>
          <span class="chip ${canWrite ? 'ok' : ''}">${canWrite ? '可维护' : '只读'}</span>
          <span class="chip">条目 ${counts[key] || 0}</span>
        </div>`;
      }).join('');
    }
    function filterByScope(key) {
      document.querySelectorAll('.scope-node').forEach(n => n.classList.remove('active-scope'));
      const nodes = document.querySelectorAll('.scope-node');
      nodes.forEach(n => { if ((n.dataset.scopeKey || '') === key) n.classList.add('active-scope'); });
      const entries = window.currentEntries || [];
      const [type, id] = key.split(':');
      const filtered = entries.filter(e => e.owner_type === type && e.owner_id === id);
      renderEntries(filtered);
      document.getElementById('scopeFilter').textContent = `当前筛选：${type} / ${id}（${filtered.length} 条）`;
    }
    function clearScopeFilter() {
      document.querySelectorAll('.scope-node').forEach(n => n.classList.remove('active-scope'));
      document.getElementById('scopeFilter').textContent = '';
      renderEntries(window.currentEntries || []);
    }
    function renderEntries(entries) {
      const root = document.getElementById('result');
      root.innerHTML = '';
      for (const item of entries) {
        const row = document.createElement('div');
        row.className = 'item';
        row.innerHTML = `<strong>${safe(item.title || item.id)}</strong><div class="meta">${safe(item.owner_type_label || item.owner_type)} / ${safe(item.owner_id)} / ${item.can_write ? '可编辑' : '只读'}</div>${item.can_write ? `<div class="actions"><button class="danger" onclick="deleteEntryById(${jsAttr(item.id)}, event)">删除</button></div>` : ''}`;
        row.onclick = () => {
          document.querySelectorAll('.item').forEach(v => v.classList.remove('active'));
          row.classList.add('active');
          document.getElementById('entryId').value = item.id;
          document.getElementById('title').value = item.title || '';
          document.getElementById('tags').value = (item.tags || []).join(', ');
          document.getElementById('editor').value = item.content || '';
          document.getElementById('saveBtn').disabled = !item.can_write;
          document.getElementById('deleteBtn').disabled = !item.can_write;
          window.selectedOpenUrl = item.open_url;
          window.selectedKnowledgeEntry = item;
        };
        root.appendChild(row);
      }
    }
    async function loadPermissions() {
      try {
        const spaceId = document.getElementById('spaceId').value.trim();
        const url = knowledgeUrl(
          `/api/v1/admin/knowledge/permissions?space_id=${encodeURIComponent(spaceId)}`,
          `/api/v1/user/knowledge/permissions?space_id=${encodeURIComponent(spaceId)}`,
          `/api/v1/knowledge/permissions?user_id=${encodeURIComponent(userId())}&space_id=${encodeURIComponent(spaceId)}`
        );
        const perm = await requestJson(url);
        window.currentPermissions = perm;
        window.defaultWriteScope = perm.default_write_scope || {owner_type:'personal', owner_id:userId()};
        document.getElementById('identity').textContent = `${perm.user_id || userId()} / ${perm.role || '未知'}`;
        document.getElementById('perm').innerHTML =
          `<span class="chip ${perm.can_manage_organization ? 'ok' : ''}">公司管理：${perm.can_manage_organization ? '是' : '否'}</span>` +
          `<span class="chip ${perm.can_manage_department ? 'ok' : ''}">部门管理：${perm.can_manage_department ? '是' : '否'}</span>` +
          `<span class="chip ${perm.can_manage_project ? 'ok' : ''}">项目管理：${perm.can_manage_project ? '是' : '否'}</span>` +
          `<div class="meta">可写范围：${safe((perm.writable_scopes || []).map(scopeLabel).join('；') || '仅可查看')}</div>`;
        document.getElementById('autoOwner').innerHTML = `<span class="chip ok">默认入库：${safe(scopeLabel(window.defaultWriteScope))}</span>`;
        // Populate scope selectors
        const writable = perm.writable_scopes || [];
        const populateSelect = (selId) => {
          const sel = document.getElementById(selId);
          sel.innerHTML = '<option value="auto">自动（系统选择）</option>';
          writable.forEach(s => {
            const option = document.createElement('option');
            option.value = scopeValue(s);
            option.textContent = scopeLabel(s);
            sel.appendChild(option);
          });
        };
        populateSelect('newOwnerType');
        populateSelect('uploadOwnerType');
        populateSelect('transferTarget');
        renderScopeGroups(perm, window.currentEntries || []);
      } catch (err) {
        setStatus('perm', String(err.message || err), true);
      }
    }
    async function loadEntries() {
      if (!document.getElementById('userId').value.trim() && params.get('user_id')) document.getElementById('userId').value = params.get('user_id');
      const query = document.getElementById('query').value.trim();
      const spaceId = document.getElementById('spaceId').value.trim();
      await loadPermissions();
      const url = knowledgeUrl(
        `/api/v1/admin/knowledge/entries?query=${encodeURIComponent(query)}&space_id=${encodeURIComponent(spaceId)}`,
        `/api/v1/user/knowledge/entries?query=${encodeURIComponent(query)}&space_id=${encodeURIComponent(spaceId)}`,
        (query ? `/api/v1/knowledge/accessible?user_id=${encodeURIComponent(userId())}&query=${encodeURIComponent(query)}&space_id=${encodeURIComponent(spaceId)}` : `/api/v1/knowledge?user_id=${encodeURIComponent(userId())}`)
      );
      const data = await requestJson(url);
      const entries = data.entries || data.results || [];
      window.currentEntries = entries;
      renderScopeGroups(window.currentPermissions || {}, entries);
      renderEntries(entries);
    }
    async function importGuides() {
      try {
        if (!hasAdminToken) throw new Error('公司级说明书导入需要管理员控制台链接');
        const data = hasAdminToken
          ? await requestJson(adminUrl('/api/v1/admin/knowledge/import/company-guides'), {method: 'POST'})
          : await requestJson(`/api/v1/knowledge/import/company-guides?user_id=${encodeURIComponent(userId())}`, {method: 'POST'});
        setStatus('guideStatus', `已导入 ${data.imported || 0} 条公司知识库文档`);
        await loadEntries();
      } catch (err) { setStatus('guideStatus', String(err.message || err), true); }
    }
    async function createEntry() {
      try {
        await loadPermissions();
        const sel = val('newOwnerType');
        const [owner_type, owner_id] = sel !== 'auto' && sel.includes(':') ? sel.split(':', 2) : ['auto', ''];
        const payload = {
          text: document.getElementById('newContent').value,
          title: document.getElementById('newTitle').value,
          owner_type, owner_id,
          tags: document.getElementById('newTags').value.split(',').map(v => v.trim()).filter(Boolean),
          user_id: userId(),
          space_id: document.getElementById('spaceId').value.trim()
        };
        const url = knowledgeUrl('/api/v1/admin/knowledge/collect', '/api/v1/user/knowledge/collect', '/api/v1/knowledge/collect');
        await requestJson(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
        setStatus('guideStatus', '新增知识条目成功');
        await loadEntries();
      } catch (err) { setStatus('guideStatus', String(err.message || err), true); }
    }
    async function uploadKnowledgeFiles() {
      try {
        await loadPermissions();
        const fileInput = document.getElementById('knowledgeFile');
        if (!fileInput.files || !fileInput.files.length) throw new Error('请先选择要上传的文档文件');
        const sel = val('uploadOwnerType');
        const [owner_type, owner_id] = sel !== 'auto' && sel.includes(':') ? sel.split(':', 2) : ['auto', ''];
        setStatus('uploadStatus', `正在上传并解析 ${fileInput.files.length} 个文件...`);
        const results = [];
        for (let i = 0; i < fileInput.files.length; i++) {
          const form = new FormData();
          form.append('file', fileInput.files[i]);
          form.append('user_id', userId());
          form.append('space_id', document.getElementById('spaceId').value.trim());
          form.append('knowledge_owner_type', owner_type);
          form.append('knowledge_owner_id', owner_id);
          const url = knowledgeUrl('/api/v1/admin/knowledge/files/upload', '/api/v1/user/knowledge/files/upload', '/api/v1/files');
          const data = await requestJson(url, {method:'POST', body:form});
          results.push(data);
        }
        setStatus('uploadStatus', `上传完成：${results.length} 个文件`);
        // Show extraction results
        const display = results.map(r => {
          const tags = (r.tags || []).join(', ');
          const summary = (r.content_preview || '').substring(0, 200);
          return `<div class="item">
            <strong>${safe(r.filename || r.id)}</strong>
            <span class="chip ${r.indexed ? 'ok' : 'bad'}">${r.indexed ? '已索引' : '未索引'}</span>
            ${r.owner_type ? `<span class="chip">${safe(scopeLabel({owner_type:r.owner_type, owner_id:r.owner_id}))}</span>` : ''}
            ${tags ? `<div class="meta">标签：${safe(tags)}</div>` : ''}
            ${summary ? `<div class="meta">内容摘要：${safe(summary)}...</div>` : ''}
          </div>`;
        }).join('');
        document.getElementById('uploadResults').innerHTML = display;
        await loadEntries();
      } catch (err) { setStatus('uploadStatus', String(err.message || err), true); }
    }
    async function updateEntry() {
      try {
      const entryId = document.getElementById('entryId').value.trim();
      const payload = {
        title: document.getElementById('title').value.trim(),
        content: document.getElementById('editor').value,
        tags: document.getElementById('tags').value.split(',').map(v => v.trim()).filter(Boolean),
        user_id: userId()
      };
      const url = knowledgeUrl(`/api/v1/admin/knowledge/${encodeURIComponent(entryId)}`, `/api/v1/user/knowledge/${encodeURIComponent(entryId)}`, `/api/v1/knowledge/${encodeURIComponent(entryId)}`);
      await requestJson(url, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      });
      setStatus('editStatus', '保存成功');
      await loadEntries();
      } catch (err) { setStatus('editStatus', String(err.message || err), true); }
    }
    async function deleteEntry() {
      try {
        const entryId = document.getElementById('entryId').value.trim();
        await deleteEntryById(entryId);
      } catch (err) { setStatus('editStatus', String(err.message || err), true); }
    }
    async function deleteEntryById(entryId, event) {
      if (event && event.stopPropagation) event.stopPropagation();
      if (!entryId) throw new Error('请先选择要删除的知识条目');
      if (!confirm(`确认删除知识条目 ${entryId}？删除后无法在知识库中继续检索。`)) return;
      const url = knowledgeUrl(`/api/v1/admin/knowledge/${encodeURIComponent(entryId)}`, `/api/v1/user/knowledge/${encodeURIComponent(entryId)}`, `/api/v1/knowledge/${encodeURIComponent(entryId)}?user_id=${encodeURIComponent(userId())}`);
      await requestJson(url, {method: 'DELETE'});
      setStatus('editStatus', '删除成功');
      document.getElementById('entryId').value = '';
      document.getElementById('title').value = '';
      document.getElementById('tags').value = '';
      document.getElementById('editor').value = '';
      document.getElementById('saveBtn').disabled = true;
      document.getElementById('deleteBtn').disabled = true;
      await loadEntries();
    }
    async function promoteEntry() {
      try {
        const entryId = document.getElementById('entryId').value.trim();
        const payload = {entry_id: entryId, target_owner_type: 'auto', target_owner_id: '', user_id: userId()};
        const url = knowledgeUrl('/api/v1/admin/knowledge/promote', '/api/v1/user/knowledge/promote', '/api/v1/knowledge/promote');
        await requestJson(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
        setStatus('editStatus', '升级成功');
        await loadEntries();
      } catch (err) { setStatus('editStatus', String(err.message || err), true); }
    }
    async function transferEntry(action) {
      try {
        const entryId = document.getElementById('entryId').value.trim();
        if (!entryId) throw new Error('请先选择一个知识条目');
        const target = val('transferTarget');
        if (!target || !target.includes(':')) throw new Error('请先选择目标知识库');
        const [target_owner_type, target_owner_id] = target.split(':', 2);
        const payload = {
          entry_id: entryId,
          action: action === 'cut' ? 'cut' : 'copy',
          target_owner_type,
          target_owner_id,
          user_id: userId()
        };
        const url = knowledgeUrl('/api/v1/admin/knowledge/transfer', '/api/v1/user/knowledge/transfer', '/api/v1/knowledge/transfer');
        const result = await requestJson(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
        setStatus('editStatus', result.action === 'cut' ? '剪切迁移成功' : '拷贝迁移成功');
        await loadEntries();
      } catch (err) { setStatus('editStatus', String(err.message || err), true); }
    }
    async function syncOrg() {
      try {
        if (!hasAdminToken) {
          setStatus('perm', '只有管理员链接可以主动同步组织架构；普通用户会在权限识别时自动使用最新缓存。', true);
          return;
        }
        const data = await requestJson(adminUrl('/api/v1/admin/org/sync'), {method:'POST'});
        setStatus('perm', data.synced ? `组织架构已同步：部门 ${data.departments || 0}，用户 ${data.users || 0}` : `无需同步：${data.reason || ''}`);
        await loadPermissions();
      } catch (err) { setStatus('perm', String(err.message || err), true); }
    }
    function openSelected() { if (window.selectedOpenUrl) window.open(window.selectedOpenUrl, '_blank'); }
    if (params.get('user_id')) document.getElementById('userId').value = params.get('user_id');
    loadEntries();
  </script>
</body>
</html>
        """
    )


@app.get("/knowledge/user", response_class=HTMLResponse)
def knowledge_user_page():
    return knowledge_management_page()


@app.get("/admin/console", response_class=HTMLResponse)
def admin_console_page(request: Request = None):
    def _html_escape(value: Any) -> str:
        text = str(value)
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
        )

    initial_identity = "未验证"
    initial_profile_box = "等待验证"
    try:
        if request is None:
            raise HTTPException(401, "missing request")
        admin_context = require_console_context_from_request(request)
        platform = _html_escape(admin_context.get("platform", "wecom"))
        user_id = _html_escape(admin_context.get("user_id", ""))
        role = _html_escape(admin_context.get("role", "admin"))
        initial_identity = f"{platform} / {user_id} / {role}"
        initial_profile_box = (
            f'<span class="chip ok">用户：{user_id}</span>'
            f'<span class="chip ok">角色：{role}</span>'
        )
    except HTTPException:
        pass

    html = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>管理员控制台</title>
  <style>
    :root {
      --accent:#0078d4; --accent-hover:#106ebe; --accent-light:#e8f4fd;
      --surface:#faf9f8; --card:#ffffff; --card-hover:#f5f5f5;
      --border:#e0e0e0; --border-focus:#0078d4;
      --text:#1a1a1a; --text-secondary:#616161; --text-tertiary:#8a8a8a;
      --error:#c42b1c; --success:#0f7b0f; --warning:#9d5d00;
      --radius:8px; --radius-sm:4px;
      --shadow:0 2px 4px rgba(0,0,0,.04),0 1px 2px rgba(0,0,0,.06);
    }
    * { box-sizing: border-box; margin:0; padding:0; }
    body { margin:0; background:var(--surface); color:var(--text); font-family:"Segoe UI Variable","Segoe UI",system-ui,-apple-system,sans-serif; font-size:14px; line-height:1.5; }
    header { padding:16px 32px; background:linear-gradient(180deg,rgba(255,255,255,.95),rgba(250,249,248,.85)); backdrop-filter:blur(12px); -webkit-backdrop-filter:blur(12px); border-bottom:1px solid var(--border); display:flex; justify-content:space-between; gap:16px; align-items:center; position:sticky; top:0; z-index:10; }
    h1 { font-size:24px; font-weight:600; letter-spacing:-.02em; }
    h2 { font-size:18px; font-weight:600; margin-bottom:12px; }
    h3 { font-size:15px; font-weight:600; margin-bottom:8px; }
    p { margin-bottom:12px; color:var(--text-secondary); font-size:13px; }
    main { display:grid; grid-template-columns:240px 1fr; gap:20px; padding:20px 32px 32px; }
    nav { background:linear-gradient(180deg,rgba(255,255,255,.9),rgba(250,249,248,.9)); backdrop-filter:blur(8px); -webkit-backdrop-filter:blur(8px); border:1px solid var(--border); border-radius:var(--radius); padding:10px; height:max-content; position:sticky; top:72px; }
    .nav-search { margin-bottom:10px; }
    .nav-search input { padding:7px 9px; font-size:12px; }
    .nav-group { margin:12px 6px 4px; padding-top:10px; border-top:1px solid var(--border); color:var(--text-tertiary); font-size:11px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; }
    .nav-group:first-of-type { margin-top:0; padding-top:0; border-top:0; }
    nav button { width:100%; text-align:left; border:0; border-radius:var(--radius-sm); background:transparent; color:var(--text); padding:8px 12px; margin:1px 0; cursor:pointer; font:inherit; font-size:13px; transition:background .1s; }
    nav button:hover { background:var(--card-hover); }
    nav button.active { background:var(--accent-light); color:var(--accent); font-weight:600; }
    section { display:none; }
    section.active { display: block; }
    .grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:14px; }
    .two { grid-template-columns:repeat(2,minmax(0,1fr)); }
    .panel { background:var(--card); border:1px solid var(--border); border-radius:var(--radius); padding:18px; box-shadow:var(--shadow); }
    .span { grid-column:1 / -1; }
    label { display:block; color:var(--text-secondary); font-size:12px; font-weight:500; margin:8px 0 4px; }
    input, textarea, select { width:100%; border:1px solid var(--border); border-radius:var(--radius-sm); padding:8px 10px; background:var(--card); color:var(--text); font:inherit; font-size:13px; transition:border-color .15s,box-shadow .15s; outline:none; }
    input:focus, textarea:focus, select:focus { border-color:var(--border-focus); box-shadow:0 0 0 3px rgba(0,120,212,.15); }
    textarea { min-height:80px; resize:vertical; }
    button, .primary { border:1px solid transparent; border-radius:var(--radius-sm); padding:7px 16px; background:var(--accent); color:#fff; font:inherit; font-size:13px; font-weight:500; cursor:pointer; transition:background .15s; }
    button:hover, .primary:hover { background:var(--accent-hover); }
    button:active { background:#005a9e; }
    button.secondary { background:var(--card); color:var(--text); border-color:var(--border); }
    button.secondary:hover { background:var(--card-hover); }
    button.tonal { background:var(--accent-light); color:var(--accent); }
    button.tonal:hover { background:#d0e8f9; }
    button.danger { background:var(--error); color:#fff; }
    button.danger:hover { background:#a3261a; }
    .table-wrap { width:100%; overflow-x:auto; }
    table { width:100%; border-collapse:collapse; font-size:13px; table-layout:fixed; }
    th { padding:10px; border-bottom:2px solid var(--border); text-align:left; font-weight:600; color:var(--text-secondary); font-size:12px; white-space:nowrap; cursor:default; }
    td { padding:10px; border-bottom:1px solid var(--border); vertical-align:top; white-space:normal; word-break:break-word; overflow-wrap:anywhere; }
    tr:hover td { background:#fafafa; }
    .mail-table { min-width:760px; table-layout:fixed; }
    .mail-table th, .mail-table td { padding:9px 10px; }
    .mail-table .cell-primary { font-weight:600; color:var(--text); line-height:1.35; }
    .mail-table .cell-secondary { color:var(--text-tertiary); font-size:12px; line-height:1.35; margin-top:2px; }
    .mail-table .mono-wrap { display:block; max-width:100%; overflow-wrap:anywhere; word-break:break-word; line-height:1.45; }
    .mail-table .status-pills { display:flex; flex-wrap:wrap; gap:4px; align-items:flex-start; }
    .mail-table .status-pills .chip { margin:0; }
    .mail-table .row-actions { display:grid; grid-template-columns:repeat(2, minmax(58px, 1fr)); gap:6px; align-items:stretch; }
    .mail-table .row-actions button { width:100%; padding:5px 8px; font-size:12px; line-height:1.2; }
    .mail-table .protocol-pill { display:inline-flex; align-items:center; border:1px solid var(--border); border-radius:var(--radius-sm); padding:2px 7px; font-size:12px; color:var(--text-secondary); background:var(--card-hover); text-transform:uppercase; }
    .chip { display:inline-flex; border-radius:var(--radius-sm); padding:3px 8px; background:#f3f3f3; color:var(--text-secondary); margin:0 4px 4px 0; font-size:12px; }
    .chip.ok { color:var(--success); background:#e8f5e9; }
    .chip.warn { color:var(--warning); background:#fef3e4; }
    .chip.bad { color:var(--error); background:#fde7e9; }
    .actions { display:flex; gap:8px; flex-wrap:wrap; margin-top:12px; }
    .status { min-height:20px; color:var(--text-secondary); font-size:12px; }
    pre { background:var(--card-hover); border-radius:var(--radius-sm); padding:10px; white-space:pre-wrap; overflow:auto; font-size:12px; }
    details { margin-top:8px; }
    details summary { cursor:pointer; color:var(--accent); font-size:12px; padding:4px 0; }
    .muted { color:var(--text-tertiary) !important; font-size:12px; }
    @media (max-width: 980px) { header, main, .grid, .two { display:block; } main { padding:0 16px 24px; } nav { position:static; margin-bottom:12px; } .panel { margin-bottom:14px; } }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>管理员控制台</h1>
      <p>统一管理企业 AI 助手。员工侧只看到一个助手，后台自动协同应用通知、Bot 前台、群聊 @、文档/待办 MCP 和知识库能力。</p>
    </div>
    <div id="identity" class="chip">未验证</div>
  </header>
  <main>
    <nav>
      <div class="nav-search"><input id="adminNavSearch" placeholder="搜索后台功能..." oninput="filterAdminNav()"></div>
      <div class="nav-group">总览</div>
      <button class="active" data-tab="overview" data-keywords="总览 首页 状态 统计" onclick="showTab('overview', this)">总览与状态</button>
      <button data-tab="integrations" data-keywords="工具 集成 状态 测试 配置 中心" onclick="showTab('integrations', this)">工具与集成中心</button>
      <div class="nav-group admin-only">用户与权限</div>
      <button data-tab="users" data-keywords="用户 权限 通讯录 人事专员 批量 开通 暂停 关闭 助手档案" onclick="showTab('users', this)">用户与权限管理</button>
      <button class="admin-only" data-tab="employees" data-keywords="快速开通 员工 AI 助手 欢迎 通知 停用" onclick="showTab('employees', this)">员工助手快速开通</button>
      <button data-tab="leaveAdmin" data-keywords="审批 假期 请假 年假 调休 人事专员 余额 负数 同步" onclick="showTab('leaveAdmin', this)">审批假期管理</button>
      <button class="admin-only" data-tab="broadcast" data-keywords="组织通知 群发 部门 全体员工 消息" onclick="showTab('broadcast', this)">组织通知</button>
      <div class="nav-group admin-only">知识与办公能力</div>
      <button class="admin-only" data-tab="knowledge" data-keywords="知识库 文档 入库 上传 说明书" onclick="showTab('knowledge', this)">知识库管理</button>
      <button class="admin-only" data-tab="mailAccounts" data-keywords="邮箱 邮件 摘要 IMAP POP3 Exchange" onclick="showTab('mailAccounts', this)">邮箱配置</button>
      <button class="admin-only" data-tab="wecomMcp" data-keywords="文档 待办 MCP 企业微信 文档能力 待办能力" onclick="showTab('wecomMcp', this)">文档/待办能力</button>
      <div class="nav-group admin-only">平台与模型</div>
      <button class="admin-only" data-tab="bots" data-keywords="平台通道 企业微信 飞书 钉钉 bot 应用 凭据" onclick="showTab('bots', this)">平台通道接入</button>
      <button class="admin-only" data-tab="models" data-keywords="模型 LLM OpenAI Anthropic DeepSeek OpenCode API Key" onclick="showTab('models', this)">模型管理</button>
      <button class="admin-only" data-tab="publicDataSources" data-keywords="公共数据源 天气 航班 汇率 RSS 新闻 物流 价格" onclick="showTab('publicDataSources', this)">公共数据源</button>
      <div class="nav-group admin-only">运维与现场系统</div>
      <button class="admin-only" data-tab="runtime" data-keywords="运行验证 服务 端口 健康 环境变量" onclick="showTab('runtime', this)">运行验证</button>
      <button class="admin-only" data-tab="ratemin" data-keywords="业务系统 软件 对接 通道 采集器 绑定 待办" onclick="showTab('ratemin', this)">业务系统软件对接</button>
      <div class="nav-group">帮助</div>
      <button data-tab="help" data-keywords="操作说明 帮助 菜单 分类 权限" onclick="showTab('help', this)">操作说明</button>
    </nav>
    <div>
       <section id="overview" class="active">
         <div class="grid">
           <div class="panel"><h3>管理员身份</h3><div id="profileBox" class="status">等待验证</div></div>
           <div class="panel"><h3>平台通道</h3><div id="platformSummary" class="status">等待加载</div></div>
           <div class="panel"><h3>服务运行</h3><div id="runtimeSummary" class="status">等待加载</div></div>
           <div class="panel"><h3>员工统计</h3><div id="userStats" class="status">等待加载</div></div>
           <div class="panel"><h3>AI 助手开通</h3><div id="botStats" class="status">等待加载</div></div>
           <div class="panel"><h3>知识库</h3><div id="knowledgeStats" class="status">等待加载</div></div>
           <div class="panel span"><h3>阶段一真实可用性</h3><div id="phase1Readiness" class="status">等待加载</div></div>
         </div>
         <div class="panel" style="margin-top:16px">
           <div class="actions">
             <button class="secondary" onclick="loadOverviewStats()">刷新全部统计</button>
             <button class="tonal" onclick="configureIntegration('users')">进入用户管理</button>
             <button class="tonal" onclick="configureIntegration('runtime')">运行验证</button>
           </div>
           <div id="statsTime" class="status"></div>
         </div>
       </section>
      <section id="integrations">
        <div class="grid">
          <div class="panel span">
            <h2>工具与集成管理中心</h2>
            <p>这是所有工具和外部能力的状态总入口。需要修改配置时，点击“配置”会跳转到对应专用页面；这里不重复保存密钥或账号，避免多处配置不一致。</p>
            <div class="actions">
              <button class="primary" onclick="loadIntegrations()">刷新全部状态</button>
              <button class="secondary" onclick="testSelectedIntegration()">测试选中项目</button>
              <select id="integrationCategoryFilter" onchange="renderIntegrationCenter()">
                <option value="">全部类别</option>
              </select>
              <select id="integrationStatusFilter" onchange="renderIntegrationCenter()">
                <option value="">全部状态</option>
                <option value="ready">正常</option>
                <option value="degraded">需关注</option>
                <option value="needs_config">需配置</option>
                <option value="blocked">阻塞</option>
                <option value="error">错误</option>
              </select>
            </div>
            <div id="integrationSummary" class="status">等待加载</div>
          </div>
          <div class="panel span">
            <h3>集成清单</h3>
            <p class="muted">“测试”会执行非破坏性检查；涉及邮箱真实读取、模型密钥保存、业务系统手工绑定等操作，仍到对应配置页完成。</p>
            <div id="integrationList">等待加载</div>
          </div>
          <div class="panel span">
            <h3>测试结果</h3>
            <div id="integrationTestResult" class="status">暂无测试</div>
          </div>
        </div>
      </section>
      <section id="bots">
        <div class="grid">
          <div class="panel span">
            <h2>企业 AI 助手平台通道接入</h2>
            <p>员工侧统一看到“企业 AI 助手”。这里用于管理员接入和诊断底层平台通道，包括主动通知、Bot 前台、群聊 @ 和文档/待办 MCP 所需凭据。只有系统提示仍缺少凭据时，才展开高级配置补录一次。</p>
            <div id="botStatus"></div>
          </div>
          <div class="panel">
            <h3>企业微信</h3>
            <label>显示名称</label><input id="wecomName" placeholder="企业 AI 助手">
            <p class="muted">默认自动复用服务器已有企业微信 Bot 和应用凭据。</p>
            <details>
              <summary>高级配置：仅在系统提示缺少凭据时填写</summary>
              <label>Bot ID</label><input id="wecom_bot_id">
              <label>Bot Secret</label><input id="wecom_bot_secret" type="password">
              <label>Corp ID</label><input id="wecom_corp_id">
              <label>Agent ID</label><input id="wecom_agent_id">
              <label>应用 Secret</label><input id="wecom_secret" type="password">
            </details>
            <div class="actions"><button class="primary" onclick="activatePlatformBot('wecom')">确认自动接管企业微信</button></div>
          </div>
          <div class="panel">
            <h3>飞书</h3>
            <label>显示名称</label><input id="feishuName" placeholder="飞书 AI 助手">
            <p class="muted">没有真实飞书租户时保持模拟状态；有凭据后平台会自动复用。</p>
            <details>
              <summary>高级配置：仅在系统提示缺少凭据时填写</summary>
              <label>App ID</label><input id="feishu_app_id">
              <label>App Secret</label><input id="feishu_app_secret" type="password">
              <label>Domain</label><select id="feishu_domain"><option value="">自动</option><option value="feishu">飞书国内</option><option value="lark">Lark 国际版</option></select>
            </details>
            <div class="actions"><button class="primary" onclick="activatePlatformBot('feishu')">确认自动接管飞书</button></div>
          </div>
          <div class="panel">
            <h3>钉钉</h3>
            <label>显示名称</label><input id="dingtalkName" placeholder="钉钉 AI 助手">
            <p class="muted">没有真实钉钉租户时保持模拟状态；有凭据后平台会自动复用。</p>
            <details>
              <summary>高级配置：仅在系统提示缺少凭据时填写</summary>
              <label>Client ID</label><input id="dingtalk_client_id">
              <label>Client Secret</label><input id="dingtalk_client_secret" type="password">
              <label>Robot Code</label><input id="dingtalk_robot_code">
            </details>
            <div class="actions"><button class="primary" onclick="activatePlatformBot('dingtalk')">确认自动接管钉钉</button></div>
          </div>
          <div class="panel span"><h3>开通结果</h3><div id="botResult" class="status">暂无操作</div></div>
        </div>
      </section>
      <section id="employees">
        <div class="grid two">
          <div class="panel">
            <h2>员工助手快速开通</h2>
            <p>这是单个员工快速开通入口。批量开通、暂停、关闭、人事专员授权和助手档案修改，请统一到“用户与权限管理”。</p>
            <p>员工只看到一个“企业 AI 助手”。管理员开通后，平台自动分配权限并发送欢迎消息；员工可直接回复欢迎消息，也可搜索同名助手或在群里 @ 同名助手。</p>
            <p class="muted">知识范围和操作权限由平台根据员工在企业 IM 中的组织架构、部门归属、负责人/管理员身份自动计算，管理员只确认开通，不手工指定范围。</p>
            <label>平台</label><select id="employeePlatform"><option value="wecom">企业微信</option><option value="feishu">飞书</option><option value="dingtalk">钉钉</option></select>
             <label>员工用户 ID</label><input id="employeeUserId" placeholder="例如 AdminUser 或同事企微 user_id">
             <label>员工姓名（可选，替代 ID 搜索）</label><input id="employeeName" placeholder="例如 张三，按姓名检索">
             <label>显示名称</label><input id="employeeBotName" placeholder="企业 AI 助手">
             <div class="actions">
               <button class="secondary" onclick="searchEmployeeByName()">按姓名查找用户</button>
               <button class="primary" onclick="activateEmployeeBot()">开通并通知员工</button>
              <button class="danger" onclick="deactivateEmployeeBot()">停用员工 AI 助手</button>
            </div>
            <div id="employeeResult" class="status"></div>
          </div>
          <div class="panel">
            <h2>已开通员工</h2>
            <div class="actions"><button class="secondary" onclick="loadEmployeeBots()">刷新列表</button></div>
            <div id="employeeList"></div>
          </div>
        </div>
      </section>
       <section id="users">
         <div class="panel">
           <h2>用户与权限管理</h2>
           <p>这是人员管理主入口。用户清单按企业 IM 通讯录组织架构同步，合并在线活跃状态、AI 助手状态、角色权限、人事专员授权、助手档案和按日/周/月/年统计的用量。</p>
           <div class="actions">
             <select id="userPlatform" style="max-width:180px"><option value="wecom">企业微信</option><option value="feishu">飞书</option><option value="dingtalk">钉钉</option></select>
             <input id="userSearch" placeholder="搜索部门、姓名、user_id..." style="max-width:240px" oninput="filterUsers()">
             <button class="secondary" onclick="loadAdminUsers(true)">同步通讯录并刷新</button>
             <button class="primary admin-only" onclick="batchSetSelectedUsers('active')">批量开通</button>
             <button class="tonal admin-only" onclick="batchSetSelectedUsers('paused')">批量暂停</button>
             <button class="danger admin-only" onclick="batchSetSelectedUsers('disabled')">批量关闭</button>
             <button class="secondary admin-only" onclick="batchSetHrSpecialists(true)">批量设为人事专员</button>
             <button class="secondary admin-only" onclick="batchSetHrSpecialists(false)">批量取消人事专员</button>
           </div>
           <div id="userBulkStatus" class="status"></div>
           <div id="assistantProfileEditor" class="panel" style="display:none; margin-top:12px; background:var(--surface); border-style:dashed">
             <h3>编辑员工助手档案</h3>
             <p class="muted">这里修改的是员工自己的 AI 助手个性化信息，不影响员工 AI 助手开通状态、组织架构权限或知识库权限。</p>
             <div class="grid two">
               <div>
                 <label>员工</label>
                 <input id="profileUserLabel" readonly>
               </div>
               <div>
                 <label>助手名称</label>
                 <input id="profileAssistantName" placeholder="例如：企业 AI 助手、小智">
               </div>
               <div>
                 <label>AI 对员工的称呼</label>
                 <input id="profileUserCallName" placeholder="例如：马总、员工甲、小韩">
               </div>
               <div>
                 <label>常用角色</label>
                 <select id="profileRoleId">
                   <option value="general">通用助手</option>
                   <option value="document_specialist">文档与制度顾问</option>
                   <option value="project_coordinator">项目与任务协同助手</option>
                   <option value="data_analyst">数据与流程分析助手</option>
                 </select>
               </div>
             </div>
             <input id="profileUserId" type="hidden">
             <div class="actions" style="margin-top:12px">
               <button class="primary" onclick="saveUserAssistantProfileFromEditor()">保存助手档案</button>
               <button class="secondary" onclick="closeUserAssistantProfileEditor()">取消</button>
             </div>
           </div>
           <div id="adminUserList"></div>
         </div>
       </section>
      <section id="leaveAdmin">
        <div class="grid two">
          <div class="panel">
            <h2>假期类型与实时同步</h2>
            <p>用于把企微请假、加班审批和本地真实假期台账保持一致。人事专员可查看和运行假期同步；管理员负责首次授权和系统配置。</p>
            <label>平台</label><select id="leavePlatform"><option value="wecom">企业微信</option><option value="feishu">飞书</option><option value="dingtalk">钉钉</option></select>
            <div class="actions">
              <button class="primary" onclick="syncLeavePolicies()">从企微同步假期类型</button>
              <button class="secondary" onclick="loadLeaveRealtimeStatus()">刷新同步状态</button>
              <button class="tonal" onclick="runLeaveRealtimeSync()">手动运行一次审批假期同步</button>
            </div>
            <div id="leaveRealtimeStatus" class="status">等待加载</div>
          </div>
          <div class="panel">
            <h2>员工动态假期提示</h2>
            <p>输入员工企业 IM 用户 ID，查看员工在 AI 助手里“我要请假”时看到的真实余额提示。</p>
            <label>员工用户 ID</label><input id="leaveNoticeUserId" placeholder="例如 AdminUser 或 UserA">
            <div class="actions"><button class="secondary" onclick="loadLeaveFormNotice()">查看动态余额提示</button></div>
            <pre id="leaveFormNotice">暂无结果</pre>
          </div>
          <div class="panel">
            <h2>调整员工假期额度</h2>
            <p>支持设置为负数。负数会保存到 Ant Colony 本地真实台账；同步到企微时会按不小于 0 的可申请额度处理。</p>
            <label>员工用户 ID</label><input id="leaveBalanceUserId" placeholder="员工企业 IM 用户 ID">
            <label>假期类型 ID</label><input id="leaveVacationId" type="number" placeholder="例如 9">
            <label>假期名称</label><input id="leaveVacationName" placeholder="例如 年假、调休假、病假">
            <label>目标余额（秒；1 天通常为 86400，可为负数）</label><input id="leaveTargetDuration" type="number" placeholder="例如 86400 或 -86400">
            <label>企微 time_attr</label><input id="leaveTimeAttr" type="number" value="1">
            <label>调整原因</label><textarea id="leaveAdjustReason" placeholder="例如 工龄年假补录、历史调休预支、病假额度修正"></textarea>
            <label><input id="leaveAllowNegative" type="checkbox" checked style="width:auto"> 允许本地保存负数余额</label>
            <div class="actions"><button class="primary" onclick="applyLeaveBalanceTarget()">保存额度调整</button></div>
            <div id="leaveAdjustResult" class="status">暂无操作</div>
          </div>
          <div class="panel">
            <h2>企微负数能力验证</h2>
            <p>用于验证企微接口是否允许负数余额。默认不写入真实企微；只有确认现场测试时才勾选真实写入。</p>
            <label>员工用户 ID</label><input id="leaveProbeUserId" placeholder="测试员工用户 ID">
            <label>假期类型 ID</label><input id="leaveProbeVacationId" type="number" placeholder="例如 9">
            <label>测试负数秒数</label><input id="leaveProbeDuration" type="number" value="-86400">
            <label><input id="leaveProbeLive" type="checkbox" style="width:auto"> 确认真实写入企微测试并恢复</label>
            <div class="actions">
              <button class="secondary" onclick="runLeaveNegativeProbe()">执行负数能力验证</button>
              <button class="secondary" onclick="loadLeaveNegativeProbeResults()">查看最近验证记录</button>
            </div>
            <div id="leaveProbeResult" class="status">暂无操作</div>
          </div>
          <div class="panel span">
            <h2>企微请假模板说明</h2>
            <p>如果企微原生表单不能动态注入个人余额，系统会尝试给请假模板添加统一说明；员工真实余额仍以 AI 助手动态查询和人事后台为准。</p>
            <label>请假模板 ID（可留空自动识别）</label><input id="leaveWorkflowTemplateId" placeholder="留空时根据最近请假审批自动识别">
            <label>说明内容</label><textarea id="leaveWorkflowNoticeText"></textarea>
            <div class="actions">
              <button class="secondary" onclick="planLeaveWorkflowNotice()">预览模板更新</button>
              <button class="primary" onclick="applyLeaveWorkflowNotice()">确认写入模板说明</button>
            </div>
            <div id="leaveWorkflowNoticeResult" class="status">暂无操作</div>
          </div>
        </div>
      </section>
      <section id="models">
        <div class="grid two">
          <div class="panel">
            <h2>模型服务商</h2>
            <label>配置名称</label><input id="modelProfileId" placeholder="default-openai">
            <label>服务商</label><select id="modelProvider"><option value="openai_compatible">OpenAI 兼容</option><option value="openai">OpenAI</option><option value="anthropic">Anthropic</option><option value="deepseek">DeepSeek</option></select>
            <label>SDK 格式</label><select id="modelSdkFormat"><option value="openai">OpenAI 格式</option><option value="anthropic">Anthropic 格式</option></select>
            <label>服务商 URL</label><input id="modelApiBase" placeholder="https://api.openai.com/v1">
            <label>API Key</label><input id="modelApiKey" type="password" placeholder="留空则保留已保存密钥">
            <label>模型名称 / ID</label><input id="modelName" placeholder="gpt-4.1-mini">
            <p class="muted">OpenCode 客户端里常见写法是 <code>opencode/&lt;model-id&gt;</code>；如果服务商 URL 是 <code>https://opencode.ai/zen/v1</code>，本系统实际调用 API 时会自动转换为 <code>&lt;model-id&gt;</code>，例如 <code>opencode/deepseek-v4-flash-free</code> 会按 <code>deepseek-v4-flash-free</code> 请求 Zen API。</p>
            <label>单次最大输出 Token（本地上限）</label><input id="modelMaxTokens" type="number" value="4096">
            <p class="muted">这里是本系统调用模型时使用的本地输出上限，不是服务商自动同步回来的上下文大小。当前 OpenCode 模型清单接口只返回模型 ID，不返回上下文或最大输出配置，所以这里需要按服务商文档或你的实际需求手工确认。</p>
            <div class="actions">
              <button class="secondary" onclick="discoverModels()">自动读取模型清单</button>
              <button class="primary" onclick="saveModelProfile()">保存模型配置</button>
            </div>
            <div id="modelActionStatus" class="status"></div>
            <div id="modelDiscovery"></div>
          </div>
          <div class="panel">
            <h2>已配置模型</h2>
            <div class="actions"><button class="secondary" onclick="loadModels()">刷新模型配置</button></div>
            <div id="modelProfiles"></div>
          </div>
        </div>
      </section>
      <section id="mailAccounts">
        <div class="grid two">
          <div class="panel">
            <h2>员工邮箱摘要配置</h2>
            <p>为员工绑定一个或多个公司邮箱读取配置。保存后系统会立即使用该员工账号实际读取最多三封邮件，显示成功或失败原因。员工在企业 AI 助手里发送“汇总今天邮件”“查找合同相关邮件”后，会按来源邮箱展示到达时间、发件人、标题、内容摘要和附件名，不支持通过企微回复邮件。</p>
            <label>平台</label><select id="mailPlatform" onchange="loadMailAccounts()"><option value="wecom">企业微信</option><option value="feishu">飞书</option><option value="dingtalk">钉钉</option></select>
            <label>员工姓名</label><input id="mailUserName" placeholder="例如 张三（优先按企业 IM 通讯录匹配）">
            <label>企业 IM 用户 ID（可选）</label><input id="mailUserId" placeholder="仅同名或未同步通讯录时填写">
            <input id="mailAccountId" type="hidden">
            <label>邮箱备注 / 用途</label><input id="mailAccountLabel" placeholder="例如 公司邮箱、业务邮箱、采购邮箱">
            <label>收邮件地址</label><input id="mailEmailAddress" placeholder="user@example.com">
            <label>协议类型</label><select id="mailProtocol"><option value="imap">IMAP</option><option value="pop3">POP3</option><option value="exchange">Exchange / Microsoft 365</option></select>
            <label>服务器地址</label><input id="mailImapHost" placeholder="imap.example.com / pop.example.com / exchange.example.com">
            <label>端口</label><input id="mailImapPort" type="number" value="993" placeholder="IMAP 常见 143/993；POP3 常见 110/995">
            <label>连接加密方式</label><select id="mailEncryption"><option value="" selected disabled>请选择（以邮箱服务商说明为准）</option><option value="ssl_tls">SSL/TLS（隐式加密）</option><option value="starttls">STARTTLS（连接后升级加密）</option><option value="none">不加密</option></select>
            <label>账号</label><input id="mailUsername" placeholder="通常同邮箱地址">
            <label>密码/授权码</label><input id="mailPassword" type="password" placeholder="留空则保留已保存密码">
            <label>文件夹</label><input id="mailFolder" value="INBOX">
            <label>查询频率（分钟）</label><input id="mailPollInterval" type="number" value="1">
            <p class="muted">新增员工邮箱时可先点“自动匹配邮箱配置”：系统会按企业 IM 通讯录邮箱和同域已配置邮箱自动补齐协议、服务器、端口、加密方式和 1 分钟监听频率；管理员只需补密码/授权码并保存测试。</p>
            <label><input id="mailEnabled" type="checkbox" checked style="width:auto"> 启用邮箱摘要</label>
            <div class="actions">
              <button class="secondary" onclick="newMailAccount()">新增邮箱</button>
              <button class="secondary" onclick="inferMailAccount()">自动匹配邮箱配置</button>
              <button class="primary" onclick="saveMailAccount()">保存并测试邮箱</button>
              <button class="secondary" onclick="testMailAccount()">重新测试读取</button>
              <button class="danger" onclick="deleteMailAccount()">删除邮箱配置</button>
            </div>
            <div id="mailAccountResult" class="status">暂无操作</div>
          </div>
          <div class="panel">
            <h2>已配置邮箱</h2>
            <p class="muted">密码不会回显；如需更换授权码，在左侧重新输入后保存。Exchange 类型先保存归属和参数，待补充 EWS 或 Microsoft Graph 凭据后启用真实读取。</p>
            <div class="actions"><button class="secondary" onclick="loadMailAccounts()">刷新邮箱配置</button></div>
            <div id="mailAccountList">等待加载</div>
          </div>
        </div>
      </section>
      <section id="publicDataSources">
        <div class="grid two">
          <div class="panel">
            <h2>公共数据源集中管理</h2>
            <p>集中查看和配置天气、空气质量、汇率、节假日、RSS、公共知识、学术、新闻舆情、航班、货运、供应链价格等数据源。内置免费源可直接测试；需要企业授权 API 的源可在这里保存配置并测试。</p>
            <p class="muted">航班、货运、供应链价格如果没有授权接口，会自动降级为联网检索兜底，并明确标注“非实时授权业务数据”。订票、物流签收、行情交易仍以官方系统为准。</p>
            <label>数据源类型</label>
            <select id="publicSourceKind" onchange="applyPublicSourceTemplate()">
              <option value="flight">航班</option>
              <option value="shipment">货运/运单</option>
              <option value="supply_price">供应链价格</option>
              <option value="fred">宏观指标 FRED</option>
              <option value="weather">天气</option>
              <option value="air_quality">空气质量</option>
              <option value="exchange_rate">汇率</option>
              <option value="holiday">节假日/工作日历</option>
              <option value="rss">RSS/公告</option>
              <option value="wikidata">Wikidata 公共知识</option>
              <option value="openalex">OpenAlex 学术</option>
              <option value="gdelt">GDELT 新闻/舆情</option>
            </select>
            <label>显示名称</label><input id="publicSourceLabel" placeholder="例如 航班查询">
            <label>来源说明</label><input id="publicSourceName" placeholder="例如 OpenSky / Aviationstack / 企业差旅平台">
            <label>接口 URL 模板</label><input id="publicSourceUrl" placeholder="https://api.example.com/search?key={secret}&q={query}">
            <label>请求方式</label><select id="publicSourceMethod"><option value="GET">GET</option><option value="POST">POST</option></select>
            <label>返回类型</label><select id="publicSourceType"><option value="json">JSON</option><option value="text">文本</option><option value="rss">RSS</option></select>
            <label>密钥/API Key</label><input id="publicSourceSecret" type="password" placeholder="留空则保留已保存密钥；URL 或 Header 可用 {secret}">
            <label>请求头 JSON</label><textarea id="publicSourceHeaders" placeholder='{"Authorization":"Bearer {secret}"}'></textarea>
            <label>GET 参数 JSON</label><textarea id="publicSourceParams" placeholder='{"query":"{query}","date":"{date}"}'></textarea>
            <label>POST 请求体 JSON</label><textarea id="publicSourceBody" placeholder='{"query":"{query}"}'></textarea>
            <label>结果字段，每行一个，格式：JSON路径:中文名</label><textarea id="publicSourceFields" placeholder="data.0.flight_no:航班号&#10;data.0.departure_time:起飞时间&#10;data.0.status:状态"></textarea>
            <label>备注</label><textarea id="publicSourceNotes" placeholder="填写接口用途、限制、费用、管理员注意事项"></textarea>
            <label><input id="publicSourceEnabled" type="checkbox" checked style="width:auto"> 启用该数据源</label>
            <div class="actions">
              <button class="secondary" onclick="applyPublicSourceTemplate()">填入推荐模板</button>
              <button class="primary" onclick="savePublicDataSource()">保存配置</button>
              <button class="secondary" onclick="testPublicDataSource()">测试当前源</button>
              <button class="danger" onclick="deletePublicDataSource()">删除外部配置</button>
            </div>
            <div id="publicDataSourceResult" class="status">暂无操作</div>
          </div>
          <div class="panel">
            <h2>已登记数据源状态</h2>
            <p class="muted">“内置”表示无需管理员配置；“已配置”表示后台有外部接口配置；“需配置”表示没有授权 API 时只能用联网检索兜底。</p>
            <div class="actions"><button class="secondary" onclick="loadPublicDataSources()">刷新状态</button></div>
            <div id="publicDataSourceList">等待加载</div>
          </div>
        </div>
      </section>
      <section id="knowledge">
        <div class="grid two">
          <div class="panel">
            <h2>公司说明书导入</h2>
            <p>将激活说明书、功能说明书、知识库管理说明书作为普通公司级文档导入公司知识库，后续统一按组织权限管理。</p>
            <button onclick="importGuides()">导入或更新公司说明书</button>
            <div id="guideResult" class="status">暂无操作</div>
          </div>
          <div class="panel">
            <h2>知识库管理入口</h2>
            <p>按当前管理员身份打开知识库管理页，用于查看、更新、删除和升级有权限的知识条目。</p>
            <button class="secondary" onclick="openKnowledgeManager()">打开知识库管理页</button>
          </div>
        </div>
      </section>
       <section id="runtime">
         <div class="panel">
           <h2>运行验证</h2>
           <p>查看服务端口、平台环境变量和健康状态。保存新凭据后如提示需要重启，应重启对应服务后再验证。</p>
           <button class="secondary" onclick="loadRuntime()">刷新运行状态</button>
           <div id="runtimeResult" class="status">等待加载</div>
         </div>
       </section>
       <section id="broadcast">
         <div class="grid two">
           <div class="panel">
             <h2>组织通知</h2>
             <p>管理员可按企业 IM 通讯录组织架构，向全体员工或指定部门内已开通企业 AI 助手且状态为 active 的员工发送消息。</p>
             <p class="muted">示例：目标填“全体员工”，内容填“注意天气”；目标填“技术部”，内容填“下班关灯”。部门会自动包含下级部门，发起管理员本人不会重复收到。</p>
             <label>平台</label><select id="broadcastPlatform"><option value="wecom">企业微信</option><option value="feishu">飞书</option><option value="dingtalk">钉钉</option></select>
             <label>组织范围</label><input id="broadcastTarget" placeholder="全体员工 / 技术部 / 部门 ID">
             <label>通知内容</label><textarea id="broadcastMessage" placeholder="要发送给员工 AI 助手会话的内容"></textarea>
             <div class="actions">
               <button class="primary" onclick="broadcastOrganization()">发送组织通知</button>
               <button class="secondary" onclick="el('broadcastMessage').value=''">清空内容</button>
             </div>
             <div id="broadcastResult" class="status">暂无操作</div>
           </div>
           <div class="panel">
             <h2>发送规则</h2>
             <p>1. 只有企业 IM 管理员可以发送。</p>
             <p>2. 通知范围以通讯录组织架构为准，部门名称和部门 ID 都可匹配。</p>
             <p>3. 只发送给已开通且未暂停的企业 AI 助手，未开通、暂停或关闭的员工会被跳过。</p>
             <p>4. 飞书和钉钉会复用同一套后端接口；没有真实租户凭据时只能通过模拟适配器验证。</p>
           </div>
         </div>
       </section>
       <section id="ratemin">
         <div class="grid two">
           <div class="panel">
             <h2>业务系统软件对接</h2>
             <p>该功能属于用户现场二次开发。采集器部署在业务系统 Windows 服务器上，只读轮询 business_a / business_b 待办池，5-10 秒内把新待办推送到员工企业 AI 助手。</p>
             <p class="muted">AI 助手只做通知和本人查询，不在业务系统中发起、同意、退回或处理流程。</p>
             <div class="actions">
               <button class="secondary" onclick="loadRateminStatus()">刷新状态</button>
               <button class="primary" onclick="recoverRateminChannel(false)">尝试恢复通道</button>
               <button class="secondary" onclick="loadRateminDirectory()">刷新目录</button>
               <button class="primary" onclick="autoBindAllRatemin()">全量自动适配</button>
             </div>
             <div id="rateminChannelStatus" class="status">通道状态等待加载</div>
             <div id="rateminStatus" class="status">等待加载</div>
           </div>
           <div class="panel">
             <h2>手工绑定</h2>
             <label>业务系统数据库</label><select id="rateminSourceDb"><option value="business_a">business_a</option><option value="business_b">business_b</option></select>
             <label>业务系统 OperID</label><input id="rateminOperId" placeholder="例如 309">
             <label>业务系统登录名</label><input id="rateminLoginName" placeholder="例如 ZHANG_Xiaolin">
             <label>业务系统显示名</label><input id="rateminDisplayName" placeholder="例如 员工甲_ZHANG Xiaolin">
             <label>企微 user_id</label><input id="rateminImUserId" placeholder="例如 AdminUser 或企微 user_id">
             <label>企微显示名</label><input id="rateminImDisplayName" placeholder="例如 张三">
             <div class="actions">
               <button class="primary" onclick="saveRateminBinding()">保存绑定</button>
               <button class="danger" onclick="removeRateminBinding()">解除绑定</button>
             </div>
             <div id="rateminBindResult" class="status">暂无操作</div>
           </div>
           <div class="panel span">
             <h2>业务系统人员目录</h2>
             <p class="muted">这里显示所有已同步到平台的业务系统人员，不只是已绑定人员。未绑定人员可以手工绑定，也可以点“全量自动适配”按企微显示名批量自动建立绑定。</p>
             <div class="grid three">
               <div>
                 <label>人员查找</label><input id="rateminDirectoryQuery" placeholder="姓名、登录名、OperID、企微账号" onkeydown="if(event.key==='Enter') loadRateminDirectory()">
               </div>
               <div>
                 <label>业务系统数据库</label><select id="rateminDirectorySourceDb"><option value="">全部</option><option value="business_a">business_a</option><option value="business_b">business_b</option></select>
               </div>
               <div>
                 <label>显示数量</label><input id="rateminDirectoryLimit" type="number" min="20" max="2000" value="500">
               </div>
             </div>
             <div class="actions">
               <button class="secondary" onclick="loadRateminDirectory()">查找/刷新</button>
               <button class="secondary" onclick="resetRateminDirectoryFilters()">清空条件</button>
             </div>
             <div id="rateminBindings">等待加载</div>
           </div>
         </div>
       </section>
       <section id="wecomMcp">
         <div class="grid two">
           <div class="panel">
             <h2>企业 AI 助手文档能力</h2>
             <p>用于让企业 AI 助手直接新建、编辑企业微信文档、智能文档、表格和智能表格。底层使用企微机器人 MCP，员工侧仍统一称为企业 AI 助手。</p>
             <p class="muted">可对机器人说：“帮我创建一份企微文档，标题是会议纪要，内容如下……”“把这段内容整理成企业微信智能文档”“把这些客户信息追加到企微表格里”。</p>
             <label>StreamableHttp URL</label><input id="wecomDocMcpUrl" type="password" placeholder="从企业微信机器人“文档”权限页面复制 StreamableHttp URL">
             <details>
               <summary>如何获取文档 MCP URL</summary>
               <p>进入企业微信管理后台或机器人配置页，打开测试机器人的“文档”可使用权限，复制 StreamableHttp URL。URL 中包含 apikey，只能粘贴到这里或服务器配置文件，不能写入 GitHub、说明书或聊天记录。</p>
               <p>启用后可支持 create_doc、smartpage_create、edit_doc_content、sheet_append_data 等能力。</p>
             </details>
           </div>
           <div class="panel">
             <h2>企业 AI 助手待办能力</h2>
             <p>用于让企业 AI 助手创建待办、查询本人待办、更新助手创建的待办、搜索待办参与人和修改参与人状态。底层使用企微机器人 MCP，员工侧仍统一称为企业 AI 助手。</p>
             <p class="muted">可对机器人说：“帮我创建一个待办，主题是提交项目体验报告，截止时间是 2026-07-14 15:00”“查一下我现在有哪些待办”“把这个待办改成已完成”“搜索张三的 userid”。</p>
             <label>StreamableHttp URL</label><input id="wecomTodoMcpUrl" type="password" placeholder="从企业微信机器人“待办”权限页面复制 StreamableHttp URL">
             <details>
               <summary>如何获取待办 MCP URL</summary>
               <p>进入企业微信管理后台或机器人配置页，打开测试机器人的“待办”可使用权限，复制 StreamableHttp URL。URL 中包含 apikey，请妥善保管；如泄露，应在企业微信中重置配置。</p>
               <p>启用后可支持 create_todo、get_todo_list、update_todo、search_todo_userid 等能力。</p>
             </details>
           </div>
           <div class="panel span">
             <h2>配置状态与验证</h2>
             <p class="muted">当前服务器已验证：文档 MCP 可创建企微在线文档并写入正文；待办 MCP 可查询、创建和删除机器人创建的待办。自然语言时间仍建议优先使用明确格式，例如 2026-07-14 15:00，后续可继续增强“明天下午3点”等口语时间解析。</p>
             <div class="actions">
               <button class="primary" onclick="saveWecomMcpConfig()">保存 MCP URL</button>
               <button class="secondary" onclick="loadWecomMcpStatus(false)">刷新配置状态</button>
               <button class="tonal" onclick="loadWecomMcpStatus(true)">发现 MCP 工具</button>
             </div>
             <div id="wecomMcpStatus" class="status">等待加载</div>
           </div>
         </div>
       </section>
       <section id="help">
         <div class="panel">
           <h2>页面操作说明</h2>
           <p>后台按职责域分组。日常先看“总览与状态”和“工具与集成中心”；人员相关统一去“用户与权限管理”；单人开通才用“员工助手快速开通”。</p>
           <table>
             <tbody>
              <tr><th>总览与状态</th><td>确认当前身份、平台状态、服务状态、员工统计、知识库状态和阶段一真实可用性。</td></tr>
              <tr><th>工具与集成中心</th><td>所有工具、数据源、企业应用连接器和现场二开通道的状态总入口。这里只做状态查看和测试，修改配置时跳转到对应专用页面。</td></tr>
              <tr><th>用户与权限管理</th><td>人员主入口。按通讯录组织架构查看员工，批量开通/暂停/关闭 AI 助手，授予或取消人事专员，编辑助手名称、称呼和角色。</td></tr>
              <tr><th>员工助手快速开通</th><td>单个员工快速开通或停用入口。批量操作和权限治理不要在这里做，统一回到“用户与权限管理”。</td></tr>
              <tr><th>审批假期管理</th><td>管理员和人事专员可用。处理假期类型同步、员工动态余额、负数假期、额度调整、审批假期实时同步和企微请假模板说明。</td></tr>
              <tr><th>组织通知</th><td>管理员按通讯录组织范围给已开通 AI 助手的员工发送通知，例如全体员工或指定部门。</td></tr>
              <tr><th>知识库管理</th><td>公司说明书导入和知识库管理入口。说明书只是公司级知识文档，新增、更新、删除、迁移均按当前组织权限执行。</td></tr>
              <tr><th>邮箱配置</th><td>管理员为员工配置一个或多个工作邮箱，支持 IMAP、POP3、Exchange，AI 助手只摘要邮件，不代发或回复。</td></tr>
              <tr><th>文档/待办能力</th><td>配置企业 AI 助手背后的企微文档和待办 MCP URL。代码仓库不保存 apikey；保存后如进程未加载新环境变量，应重启相关服务。</td></tr>
              <tr><th>平台通道接入</th><td>管理员接入企业微信、飞书、钉钉底层通道。员工仍只看到“企业 AI 助手”。</td></tr>
              <tr><th>模型管理</th><td>管理员配置模型服务商 URL、API Key、模型 ID 和默认模型。</td></tr>
              <tr><th>公共数据源</th><td>管理员配置天气、航班、汇率、RSS、物流、供应链价格等外部公共数据源。</td></tr>
              <tr><th>运行验证</th><td>检查服务端口、环境变量和健康状态。飞书、钉钉没有真实账号时只能看模拟或缺凭据状态。</td></tr>
              <tr><th>业务系统软件对接</th><td>现场二开功能。Windows 采集器只读业务系统数据库，新待办提交到平台后按绑定关系推送到员工企业 AI 助手。</td></tr>
              <tr><th>权限说明</th><td>管理员可看到全部菜单；人事专员只看到总览、用户查看、审批假期管理和操作说明。</td></tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  </main>
  <script>
    (function () {
      function query(name) {
        var match = new RegExp('[?&]' + name + '=([^&]*)').exec(window.location.search);
        return match ? decodeURIComponent(match[1].replace(/\\+/g, ' ')) : '';
      }
      var platform = query('platform') || 'wecom';
      var userId = query('user_id');
      var token = query('admin_token');
      if (!userId || !token || !window.XMLHttpRequest) return;
      var xhr = new XMLHttpRequest();
      xhr.open('GET', '/api/v1/admin/profile?platform=' + encodeURIComponent(platform) + '&user_id=' + encodeURIComponent(userId) + '&admin_token=' + encodeURIComponent(token), true);
      xhr.onreadystatechange = function () {
        if (xhr.readyState !== 4) return;
        var identity = document.getElementById('identity');
        var profileBox = document.getElementById('profileBox');
        if (!identity || !profileBox) return;
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            var profile = JSON.parse(xhr.responseText || '{}');
            identity.textContent = (profile.platform || platform) + ' / ' + (profile.user_id || userId) + ' / ' + (profile.role || 'admin');
            profileBox.textContent = '用户：' + (profile.user_id || userId) + ' / 角色：' + (profile.role || 'admin');
          } catch (err) {
            identity.textContent = '已验证';
            profileBox.textContent = '管理员身份已验证';
          }
        } else {
          identity.textContent = '验证失败';
          profileBox.textContent = '验证失败，请从 Bot 重新打开管理员控制台';
        }
      };
      xhr.send();
    })();
  </script>
  <script>
    const params = new URLSearchParams(location.search);
    // Move token from URL to sessionStorage for security
    const urlToken = params.get('admin_token');
    if (urlToken) {
      sessionStorage.setItem('admin_token', urlToken);
      const newParams = new URLSearchParams(location.search);
      newParams.delete('admin_token');
      const newUrl = location.pathname + (newParams.toString() ? '?' + newParams.toString() : '');
      history.replaceState(null, '', newUrl);
    }
    const getToken = () => sessionStorage.getItem('admin_token') || '';
    const authQuery = () => `platform=${encodeURIComponent(params.get('platform') || 'wecom')}&user_id=${encodeURIComponent(params.get('user_id') || '')}`;
    const authHeaders = () => {
      const h = {
        'X-Platform': params.get('platform') || 'wecom',
        'X-User-ID': params.get('user_id') || '',
      };
      const t = getToken();
      if (t) h['X-Admin-Token'] = t;
      return h;
    };
    const el = (id) => document.getElementById(id);
    const val = (id) => { const node = el(id); return ((node && node.value) || '').trim(); };
    const safe = (value) => String(value == null ? '' : value).replace(/[&<>\"']/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[ch]));
    function showTab(id, btn) {
      const target = el(id);
      if (!target) return;
      const navButton = btn || document.querySelector(`nav button[data-tab="${id}"]`);
      document.querySelectorAll('section').forEach((section) => section.classList.remove('active'));
      document.querySelectorAll('nav button').forEach((button) => button.classList.remove('active'));
      target.classList.add('active');
      if (navButton) navButton.classList.add('active');
      if (id === 'integrations') loadIntegrations();
      if (id === 'mailAccounts') loadMailAccounts();
      if (id === 'leaveAdmin') loadLeaveRealtimeStatus();
      if (id === 'ratemin') {
        loadRateminStatus();
        startRateminChannelAutoRefresh();
      } else {
        stopRateminChannelAutoRefresh();
      }
    }
    function filterAdminNav() {
      const term = (val('adminNavSearch') || '').toLowerCase();
      document.querySelectorAll('nav button[data-tab]').forEach((button) => {
        if (button.dataset.roleHidden === '1') {
          button.style.display = 'none';
          return;
        }
        const text = `${button.textContent || ''} ${button.dataset.keywords || ''}`.toLowerCase();
        button.style.display = !term || text.includes(term) ? '' : 'none';
      });
      updateNavGroupVisibility();
    }
    function updateNavGroupVisibility() {
      const children = Array.from(document.querySelector('nav').children);
      for (let i = 0; i < children.length; i += 1) {
        const node = children[i];
        if (!node.classList || !node.classList.contains('nav-group')) continue;
        let visibleButton = false;
        for (let j = i + 1; j < children.length; j += 1) {
          const next = children[j];
          if (next.classList && next.classList.contains('nav-group')) break;
          if (next.tagName === 'BUTTON' && next.style.display !== 'none') {
            visibleButton = true;
            break;
          }
        }
        node.style.display = visibleButton ? '' : 'none';
      }
    }
    async function api(path, options = {}) {
      const merged = { ...options, headers: { ...(options.headers || {}), ...authHeaders() } };
      const resp = await fetch(path, merged);
      const contentType = resp.headers.get('content-type') || '';
      const data = contentType.includes('application/json') ? await resp.json() : {detail: await resp.text()};
      if (!resp.ok) throw new Error(data.detail || data.error || JSON.stringify(data));
      return data;
    }
    function chip(text, cls='') { return `<span class="chip ${safe(cls)}">${safe(text)}</span>`; }
    function jsString(value) { return JSON.stringify(String(value == null ? '' : value)); }
    function jsAttr(value) { return safe(jsString(value)); }
    function sortHeader(key, label) { return `${label} <span style="cursor:pointer;font-size:11px" onclick="sortUsers('${key}')">${userSortKey===key ? (userSortAsc ? '▲' : '▼') : '⇅'}</span>`; }
    function setHtml(id, html) { el(id).innerHTML = html; }
    function setText(id, text, bad=false) {
      const node = el(id);
      node.textContent = text;
      node.style.color = bad ? 'var(--error)' : 'var(--text-secondary)';
    }
    function table(headers, rows) {
      const head = headers.map((item) => `<th>${safe(item)}</th>`).join('');
      const body = rows.length ? rows.join('') : `<tr><td colspan="${headers.length}">暂无数据</td></tr>`;
      return `<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
    }
    const rateminDirectoryState = { sort: 'source_db', direction: 'asc' };
    let rateminChannelRefreshTimer = null;
    let rateminAutoRecovering = false;
    let rateminLastAutoRecoverAt = 0;
    function rateminStatusLabel(status) {
      if (status === 'healthy') return chip('正常', 'ok');
      if (status === 'degraded') return chip('需关注', 'warn');
      return chip('异常', 'bad');
    }
    function rateminOriginLabel(origin) {
      const labels = {
        none: '无异常',
        ratemin_server: '业务系统服务器侧',
        project_server: '项目服务器侧',
        mixed: '两侧都可能异常'
      };
      return labels[origin] || origin || '未知';
    }
    function renderManualSteps(title, steps) {
      const items = (steps || []).map((step) => `<li>${safe(step)}</li>`).join('');
      return `<details><summary>${safe(title)}</summary><ol>${items}</ol></details>`;
    }
    function renderRateminChannelStatus(data) {
      const ratemin = data.ratemin_server || {};
      const project = data.project_server || {};
      const sourceRows = (ratemin.current_events || []).map((item) =>
        `<tr><td>${safe(item.source_db)}</td><td>${safe(item.count || 0)}</td><td>${safe(item.age_seconds == null ? '-' : item.age_seconds + ' 秒')}</td></tr>`
      );
      const pendingRows = (project.pending_status || []).map((item) =>
        `<tr><td>${safe(item.delivery_status || '-')}</td><td>${safe(item.count || 0)}</td></tr>`
      );
      const manual = data.manual_steps || {};
      setHtml('rateminChannelStatus',
        `<h3>通道状态 ${rateminStatusLabel(data.overall_status)}</h3>` +
        `<p>${chip(`问题归属：${rateminOriginLabel(data.problem_origin)}`, data.problem_origin === 'none' ? 'ok' : 'warn')}` +
        `${chip(`自动恢复：${data.auto_recovery_available ? '已配置' : '未配置唤醒命令'}`, data.auto_recovery_available ? 'ok' : 'warn')}</p>` +
        `<div class="grid two"><div><h4>业务系统 Windows 服务器</h4><p>${rateminStatusLabel(ratemin.status)} ${safe(ratemin.summary || '')}</p>` +
        table(['数据源','当前待办数','最近同步'], sourceRows) +
        `</div><div><h4>项目服务器</h4><p>${rateminStatusLabel(project.status)} ${safe(project.summary || '')}</p>` +
        table(['通知状态','数量'], pendingRows) +
        `</div></div>` +
        renderManualSteps('项目服务器人工恢复步骤', manual.project_server || []) +
        renderManualSteps('业务系统 Windows 服务器人工恢复步骤', manual.ratemin_server || [])
      );
    }
    async function loadRateminChannelStatus(autoRecover=true) {
      try {
        const data = await api(`/api/v1/admin/ratemin/channel-status?platform=${encodeURIComponent(params.get('platform') || 'wecom')}`);
        renderRateminChannelStatus(data);
        const now = Date.now();
        if (autoRecover && data.overall_status !== 'healthy' && !rateminAutoRecovering && now - rateminLastAutoRecoverAt > 120000) {
          rateminLastAutoRecoverAt = now;
          recoverRateminChannel(true);
        }
      } catch (err) {
        setText('rateminChannelStatus', String(err.message || err), true);
      }
    }
    async function recoverRateminChannel(autoTriggered=false) {
      try {
        rateminAutoRecovering = true;
        setHtml('rateminChannelStatus', chip(autoTriggered ? '检测到异常，正在自动尝试恢复' : '正在尝试恢复通道', 'warn'));
        const data = await api(`/api/v1/admin/ratemin/recover?platform=${encodeURIComponent(params.get('platform') || 'wecom')}`, {method:'POST'});
        renderRateminChannelStatus(data.status_after_recovery || {});
        const project = data.project_recovery || {};
        setHtml('rateminBindResult',
          chip(autoTriggered ? '已自动尝试恢复' : '已手动尝试恢复', 'ok') +
          chip(`补发检查 ${safe(project.checked || 0)} 条`) +
          chip(`已发送 ${safe(project.sent || 0)} 条`, 'ok') +
          (project.failed ? chip(`失败 ${safe(project.failed)} 条`, 'bad') : '')
        );
        await loadRateminStatus();
      } catch (err) {
        setText('rateminChannelStatus', String(err.message || err), true);
      } finally {
        rateminAutoRecovering = false;
      }
    }
    function startRateminChannelAutoRefresh() {
      loadRateminChannelStatus(true);
      if (rateminChannelRefreshTimer) return;
      rateminChannelRefreshTimer = setInterval(() => loadRateminChannelStatus(true), 30000);
    }
    function stopRateminChannelAutoRefresh() {
      if (!rateminChannelRefreshTimer) return;
      clearInterval(rateminChannelRefreshTimer);
      rateminChannelRefreshTimer = null;
    }
    function rateminSortHeader(key, label) {
      const active = rateminDirectoryState.sort === key;
      const icon = active ? (rateminDirectoryState.direction === 'asc' ? '▲' : '▼') : '⇅';
      return `<button class="secondary" style="padding:3px 8px;font-size:12px" onclick="sortRateminDirectory(${jsAttr(key)})">${safe(label)} ${icon}</button>`;
    }
    function renderRateminDirectoryTable(entries) {
      const headers = [
        rateminSortHeader('source_db', '数据库'),
        rateminSortHeader('rate_oper_id', 'OperID'),
        rateminSortHeader('rate_display_name', '业务系统用户'),
        rateminSortHeader('directory_status', '绑定状态'),
        rateminSortHeader('match_method', '匹配方式'),
        rateminSortHeader('im_display_name', '企微用户'),
        rateminSortHeader('snapshot_updated_at', '同步时间'),
        '操作'
      ];
      const rows = entries.map((item) => {
        const state = item.directory_status === 'bound' ? chip('已绑定', 'ok') : chip('未绑定', 'warn');
        const matchMethod = item.match_method ? safe(item.match_method) : '-';
        return `<tr><td>${safe(item.source_db)}</td><td>${safe(item.rate_oper_id)}</td><td>${safe(item.rate_display_name || '-')}<br><span class="chip">${safe(item.rate_login_name || '-')}</span></td><td>${state}</td><td><span class="chip">${matchMethod}</span></td><td>${safe(item.im_display_name || '-')}<br><span class="chip">${safe(item.im_user_id || '-')}</span></td><td>${safe(item.snapshot_updated_at || '-')}</td><td><button class="secondary" onclick="fillRateminBinding(${jsAttr(item.source_db)},${jsAttr(item.rate_oper_id)},${jsAttr(item.rate_login_name||'')},${jsAttr(item.rate_display_name||'')},${jsAttr(item.im_user_id||'')},${jsAttr(item.im_display_name||'')})">编辑</button></td></tr>`;
      });
      const body = rows.length ? rows.join('') : `<tr><td colspan="${headers.length}">暂无匹配人员</td></tr>`;
      return `<table><thead><tr>${headers.map((item) => `<th>${item}</th>`).join('')}</tr></thead><tbody>${body}</tbody></table>`;
    }
    function sortRateminDirectory(key) {
      if (rateminDirectoryState.sort === key) {
        rateminDirectoryState.direction = rateminDirectoryState.direction === 'asc' ? 'desc' : 'asc';
      } else {
        rateminDirectoryState.sort = key;
        rateminDirectoryState.direction = 'asc';
      }
      loadRateminDirectory();
    }
    function resetRateminDirectoryFilters() {
      el('rateminDirectoryQuery').value = '';
      el('rateminDirectorySourceDb').value = '';
      el('rateminDirectoryLimit').value = '500';
      rateminDirectoryState.sort = 'source_db';
      rateminDirectoryState.direction = 'asc';
      loadRateminDirectory();
    }
    function hasNonAscii(value) {
      return Array.from(String(value || '')).some((ch) => ch.charCodeAt(0) > 127);
    }
    function defaultEmployeeBotName(platform) {
      if (platform === 'feishu') return '飞书 AI 助手';
      if (platform === 'dingtalk') return '钉钉 AI 助手';
      return '企业 AI 助手';
    }
    function isDamagedDisplayName(value) {
      const text = String(value || '').trim();
      if (!text) return false;
      return text.includes('??????????') || text.includes('�') || text.includes('锟') || text.includes('Ã') || text.includes('Â');
    }
    async function ensureAdminUsersLoaded() {
      if (!Array.isArray(window.allUsers)) {
        await loadAdminUsers(false);
      }
    }
    async function loadProfile() {
      const profile = await api('/api/v1/admin/profile');
      window.consoleProfile = profile;
      el('identity').textContent = `${profile.platform} / ${profile.user_id} / ${profile.role}`;
      setHtml('profileBox', [
        chip(`用户：${profile.user_id}`, 'ok'),
        chip(`角色：${profile.role}`, 'ok'),
        chip(`部门：${(profile.departments || []).join(', ') || '-'}`)
      ].join(''));
      applyConsoleRoleVisibility(profile);
      return profile;
    }
    function applyConsoleRoleVisibility(profile) {
      if (!profile || profile.role !== 'hr_specialist') return;
      const allowed = new Set(['overview', 'users', 'leaveAdmin', 'help']);
      document.querySelectorAll('nav button').forEach((button) => {
        const tab = button.dataset.tab || '';
        if (tab && !allowed.has(tab)) {
          button.dataset.roleHidden = '1';
          button.style.display = 'none';
        }
      });
      document.querySelectorAll('.admin-only').forEach((node) => { node.style.display = 'none'; });
      filterAdminNav();
      setHtml('platformSummary', chip('人事专员受限后台', 'warn'));
      setHtml('runtimeSummary', '该角色只开放用户查看和审批假期管理。');
    }
    async function loadBots() {
      const data = await api('/api/v1/admin/platform/bots');
      const platforms = data.platforms || [];
      const enabled = platforms.filter((platform) => platform.enabled).length;
      setHtml('platformSummary', chip(`已启用平台：${enabled}`, enabled ? 'ok' : 'warn') + chip(`总平台：${platforms.length}`));
      const rows = platforms.map((platform) => {
        const sourceText = Object.entries(platform.credential_sources || {}).map(([key, source]) => `${key}: ${source}`).join('; ') || '-';
        return `<tr><td>${safe(platform.platform_label || platform.platform)}</td><td>${platform.enabled ? chip('已启用','ok') : chip('待确认','warn')}</td><td>${safe((platform.configured_keys || []).join(', ') || '-')}</td><td>${safe((platform.missing_keys || []).join(', ') || '-')}</td><td>${safe(sourceText)}</td><td>${platform.restart_required ? chip('需要','bad') : chip('不需要','ok')}</td><td>${safe(platform.next_action || '-')}</td></tr>`;
      });
      setHtml('botStatus', table(['平台','状态','已配置','缺少配置','自动发现来源','重启','下一步'], rows));
    }
    function platformCredentials(platform) {
      if (platform === 'wecom') return {bot_id:val('wecom_bot_id'), bot_secret:val('wecom_bot_secret'), corp_id:val('wecom_corp_id'), agent_id:val('wecom_agent_id'), secret:val('wecom_secret')};
      if (platform === 'feishu') return {app_id:val('feishu_app_id'), app_secret:val('feishu_app_secret'), domain:val('feishu_domain')};
      return {client_id:val('dingtalk_client_id'), client_secret:val('dingtalk_client_secret'), robot_code:val('dingtalk_robot_code')};
    }
    async function activatePlatformBot(platform) {
      const nameMap = {wecom:val('wecomName'), feishu:val('feishuName'), dingtalk:val('dingtalkName')};
      const payload = {credentials: platformCredentials(platform), display_name: nameMap[platform] || '', visibility_scope: 'all', auto_permissions: ['docs.full','knowledge.readwrite','contacts.read']};
      try {
        const data = await api(`/api/v1/admin/platform/bots/${platform}/activate`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
        const sources = Object.entries(data.credential_sources || {}).map(([key, source]) => `${key}: ${source}`).join('；') || '未返回来源';
        setHtml('botResult', chip(`${data.display_name || platform} 已自动接管`, 'ok') + chip(data.restart_required ? '需要重启' : '当前可测试', data.restart_required ? 'warn' : 'ok') + `<p>${safe(data.next_action || '')}</p><p>自动发现来源：${safe(sources)}</p>`);
        await loadBots();
      } catch (err) {
        setText('botResult', String(err.message || err), true);
      }
    }
    async function loadEmployeeBots() {
      try {
        const data = await api('/api/v1/admin/employee-bots');
        await ensureAdminUsersLoaded();
        // Build user name map from loaded user data
        const nameMap = {};
        if (window.allUsers) {
          window.allUsers.forEach(u => { nameMap[u.user_id] = u.name || ''; });
        }
        const rows = (data.assignments || []).map((assignment) => {
          const rawDisplayName = String(assignment.display_name || '').trim();
          const isGarbled = isDamagedDisplayName(rawDisplayName);
          const fixedName = rawDisplayName && !isGarbled ? rawDisplayName : defaultEmployeeBotName(assignment.platform);
          const empName = nameMap[assignment.user_id] || '';
          const employeeMain = empName || assignment.user_id;
          const accountLine = empName && empName !== assignment.user_id ? `<br><span style="font-size:11px;color:#8a8a8a">${safe(assignment.user_id)}</span>` : '';
          const notifLabels = {not_requested:'未请求', sent:'已发送', failed:'发送失败', pending:'待发送'};
          const notif = notifLabels[assignment.notify_status] || assignment.notify_status || '-';
          const notifHint = assignment.notify_status === 'not_requested' ? '（开通时未勾选通知）' : '';
          return `<tr>
            <td>${safe(assignment.platform)}</td>
            <td>${safe(employeeMain)}${accountLine}</td>
            <td><span id="empname_${safe(assignment.user_id).replace(/[^a-zA-Z0-9\u4e00-\u9fff]/g,'_')}">${safe(fixedName)}</span>
              ${isGarbled ? '<span class="chip bad" title="名称已损坏，点击编辑修复">需修复</span>' : ''}
              <button class="secondary" onclick="editEmployeeNameFix(${jsAttr(assignment.platform)},${jsAttr(assignment.user_id)},${jsAttr(fixedName)})" style="font-size:11px;padding:2px 8px;margin-left:4px">编辑</button></td>
            <td>${safe(assignment.scope)}</td>
            <td>${assignment.status === 'active' ? chip('已开通','ok') : chip('已停用','bad')}</td>
            <td title="开通时是否向员工发送通知消息">${safe(notif)}<span style="font-size:10px;color:#8a8a8a">${notifHint}</span>
              <button class="secondary" onclick="sendEmployeeWelcome(${jsAttr(assignment.platform)},${jsAttr(assignment.user_id)},${jsAttr(fixedName)})" style="font-size:11px;padding:2px 8px;margin-left:4px">重发欢迎</button></td>
          </tr>`;
        });
        setHtml('employeeList', table(['平台','员工','AI 助手名称','自动范围','状态','通知'], rows));
      } catch (err) {
        setText('employeeResult', String(err.message || err), true);
      }
    }
    async function editEmployeeNameFix(platform, userId, currentName) {
      const newName = prompt('编辑 AI 助手显示名称：', currentName);
      if (newName === null || newName === currentName) return;
      try {
        const form = new URLSearchParams();
        form.append('platform', platform);
        form.append('user_id', userId);
        form.append('display_name', newName);
        const url = `/api/v1/admin/employee-bots/rename?${authQuery()}`;
        await fetch(url, {method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:form});
        await loadEmployeeBots();
      } catch (err) { alert('修改失败：' + String(err.message || err)); }
    }
    let userSortKey = '', userSortAsc = true;
    function sortUsers(key) {
      if (userSortKey === key) { userSortAsc = !userSortAsc; } else { userSortKey = key; userSortAsc = true; }
      renderUserTable();
    }
    function filterUsers() { renderUserTable(); }
    function renderUserTable() {
      const search = (val('userSearch') || '').toLowerCase();
      let users = window.allUsers || [];
      if (search) users = users.filter(u => (u.department_path||'').toLowerCase().includes(search) || (u.name||'').toLowerCase().includes(search) || (u.user_id||'').toLowerCase().includes(search) || (u.assistant_name||'').toLowerCase().includes(search) || (u.assistant_user_call_name||'').toLowerCase().includes(search));
      if (userSortKey) users = [...users].sort((a,b) => {
        const va = (a[userSortKey] || '').toString().toLowerCase(), vb = (b[userSortKey] || '').toString().toLowerCase();
        return userSortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
      });
      const mkHeader = (key,label) => `<th onclick="sortUsers('${key}')" style="cursor:pointer">${label}${userSortKey===key ? (userSortAsc ? ' ▲' : ' ▼') : ''}</th>`;
      const rows = users.map((user) => {
        const usage = user.usage || {};
        const checked = `<input type="checkbox" class="user-check" value="${safe(user.user_id)}">`;
        const bot = user.bot_status === 'active' ? chip('已开通','ok') : (user.bot_status === 'paused' ? chip('已暂停','warn') : (user.bot_status === 'disabled' ? chip('已关闭','bad') : chip('未开通','warn')));
        const online = user.online_status === 'recently_active' ? chip('近期活跃','ok') : chip(user.online_status || '未知');
        const assistantName = user.assistant_name || user.bot_display_name || defaultEmployeeBotName(user.platform || val('userPlatform') || 'wecom');
        const callName = user.assistant_user_call_name || '-';
        const roleName = user.assistant_role_name || '通用助手';
        const profileCell = `<div><b>${safe(assistantName)}</b></div><div class="muted">称呼用户：${safe(callName)}</div><div class="muted">角色：${safe(roleName)}</div>`;
        const profileActions = `<button class="secondary" onclick="openUserAssistantProfileEditor(${jsAttr(user.user_id)},${jsAttr(user.name || user.user_id)},${jsAttr(assistantName)},${jsAttr(user.assistant_user_call_name || '')},${jsAttr(user.assistant_role_id || 'general')})">编辑档案</button> <button class="danger" onclick="deleteUserAssistantProfile(${jsAttr(user.user_id)})">删除档案</button>`;
        const permissionCell = `${user.is_admin ? chip('管理员','ok') : ''}${user.is_leader ? chip('负责人','warn') : chip('员工')}${user.is_hr_specialist ? chip('人事专员','ok') : ''}`;
        const isHrOnly = (window.consoleProfile || {}).role === 'hr_specialist';
        const hrAction = user.is_hr_specialist
          ? `<button class="secondary" onclick="setHrSpecialist(${jsAttr(user.user_id)},false)">取消人事专员</button>`
          : `<button class="secondary" onclick="setHrSpecialist(${jsAttr(user.user_id)},true)">设为人事专员</button>`;
        const adminActions = `<button class="secondary admin-only" onclick="setOneUserBot(${jsAttr(user.user_id)},'active')">开通</button> <button class="tonal admin-only" onclick="setOneUserBot(${jsAttr(user.user_id)},'paused')">暂停</button> <button class="danger admin-only" onclick="setOneUserBot(${jsAttr(user.user_id)},'disabled')">关闭</button> <span class="admin-only">${hrAction} ${profileActions}</span>`;
        const hrActions = `<button class="secondary" onclick="el('leaveBalanceUserId').value=${jsAttr(user.user_id)}; el('leaveNoticeUserId').value=${jsAttr(user.user_id)}; showTab('leaveAdmin', document.querySelector('nav button[data-tab=&quot;leaveAdmin&quot;]'));">查看/调整假期</button>`;
        return `<tr><td>${checked}</td><td>${safe(user.department_path || '-')}</td><td>${safe(user.name || user.user_id)}<br><span class="chip">${safe(user.user_id)}</span></td><td>${permissionCell}</td><td>${online}</td><td>${bot}</td><td>${profileCell}</td><td>日 ${safe((usage.day || {}).estimated_tokens || 0)} / 周 ${safe((usage.week || {}).estimated_tokens || 0)} / 月 ${safe((usage.month || {}).estimated_tokens || 0)} / 年 ${safe((usage.year || {}).estimated_tokens || 0)}</td><td>${isHrOnly ? hrActions : adminActions}</td></tr>`;
      });
      const headers = ['选择', `${sortHeader('department_path','部门')}`, `${sortHeader('name','用户')}`, `${sortHeader('is_admin','权限')}`, `${sortHeader('online_status','状态')}`, `${sortHeader('bot_status','AI 助手状态')}`, '助手档案', 'Token 估算', '操作'];
      const headerRow = `<tr>${headers.map(h => `<th>${h}</th>`).join('')}</tr>`;
      setHtml('adminUserList', `<table><thead>${headerRow}</thead><tbody>${rows.length ? rows.join('') : '<tr><td colspan="'+headers.length+'">暂无匹配用户</td></tr>'}</tbody></table>`);
    }
    async function loadAdminUsers(sync=false) {
      try {
        const platform = val('userPlatform') || params.get('platform') || 'wecom';
        const data = await api(`/api/v1/admin/users?platform=${encodeURIComponent(platform)}&sync=${sync ? 'true' : 'false'}`);
        window.allUsers = data.users || [];
        renderUserTable();
      } catch (err) {
        setText('userBulkStatus', String(err.message || err), true);
      }
    }
    function selectedUserIds() {
      return Array.from(document.querySelectorAll('.user-check:checked')).map((item) => item.value);
    }
    async function setOneUserBot(userId, status) {
      const platform = val('userPlatform') || params.get('platform') || 'wecom';
      const payload = {platform, user_id:userId, status, display_name:'企业 AI 助手', notify: status === 'active'};
      await api('/api/v1/admin/employee-bots/status', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
      await loadAdminUsers(false);
    }
    function openUserAssistantProfileEditor(userId, userName, currentAssistantName, currentCallName, currentRoleId) {
      document.getElementById('profileUserId').value = userId || '';
      document.getElementById('profileUserLabel').value = `${userName || userId || ''}（${userId || ''}）`;
      document.getElementById('profileAssistantName').value = currentAssistantName || '企业 AI 助手';
      document.getElementById('profileUserCallName').value = currentCallName || '';
      document.getElementById('profileRoleId').value = currentRoleId || 'general';
      document.getElementById('assistantProfileEditor').style.display = 'block';
      document.getElementById('profileAssistantName').focus();
    }
    function closeUserAssistantProfileEditor() {
      document.getElementById('assistantProfileEditor').style.display = 'none';
      document.getElementById('profileUserId').value = '';
    }
    async function saveUserAssistantProfileFromEditor() {
      try {
        const userId = val('profileUserId');
        if (!userId) throw new Error('请先选择要编辑的员工');
        const payload = {
          platform: val('userPlatform') || params.get('platform') || 'wecom',
          user_id: userId,
          assistant_name: val('profileAssistantName') || '企业 AI 助手',
          user_call_name: val('profileUserCallName'),
          role_id: val('profileRoleId') || 'general'
        };
        const data = await api('/api/v1/admin/users/assistant-profile', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
        const profile = data.profile || {};
        closeUserAssistantProfileEditor();
        setHtml('userBulkStatus', chip(`已更新 ${safe(userId)} 的助手档案：${safe(profile.assistant_name || '-')} / 称呼用户：${safe(profile.user_call_name || '-')} / 角色：${safe(profile.role_name || '-')}`, 'ok'));
        await loadAdminUsers(false);
      } catch (err) {
        setText('userBulkStatus', String(err.message || err), true);
      }
    }
    async function deleteUserAssistantProfile(userId) {
      try {
        const platform = val('userPlatform') || params.get('platform') || 'wecom';
        if (!confirm(`确认删除 ${userId} 的助手名、称呼和角色设置？删除后会恢复默认档案。`)) return;
        const data = await api(`/api/v1/admin/users/assistant-profile/${encodeURIComponent(platform)}/${encodeURIComponent(userId)}`, {method:'DELETE'});
        setHtml('userBulkStatus', chip(data.deleted ? `已删除 ${safe(userId)} 的助手档案` : `${safe(userId)} 没有自定义助手档案`, 'warn'));
        await loadAdminUsers(false);
      } catch (err) {
        setText('userBulkStatus', String(err.message || err), true);
      }
    }
    async function batchSetSelectedUsers(status) {
      try {
        const user_ids = selectedUserIds();
        if (!user_ids.length) throw new Error('请先勾选用户');
        const payload = {platform: val('userPlatform') || params.get('platform') || 'wecom', user_ids, status, display_name:'企业 AI 助手', notify: status === 'active'};
        const data = await api('/api/v1/admin/employee-bots/batch', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
        setHtml('userBulkStatus', chip(`已更新 ${data.updated || 0} 个用户`, 'ok'));
        await loadAdminUsers(false);
      } catch (err) {
        setText('userBulkStatus', String(err.message || err), true);
      }
    }
    async function setHrSpecialist(userId, enabled) {
      try {
        const platform = val('userPlatform') || params.get('platform') || 'wecom';
        const data = await api('/api/v1/admin/hr-specialists', {
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({platform, user_id:userId, enabled})
        });
        const action = data.specialist && data.specialist.enabled ? '已设为人事专员' : '已取消人事专员';
        setHtml('userBulkStatus', chip(`${safe(userId)} ${action}`, 'ok'));
        await loadAdminUsers(false);
      } catch (err) {
        setText('userBulkStatus', String(err.message || err), true);
      }
    }
    async function batchSetHrSpecialists(enabled) {
      try {
        const user_ids = selectedUserIds();
        if (!user_ids.length) throw new Error('请先勾选用户');
        const platform = val('userPlatform') || params.get('platform') || 'wecom';
        const data = await api('/api/v1/admin/hr-specialists/batch', {
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({platform, user_ids, enabled})
        });
        setHtml('userBulkStatus', chip(`${enabled ? '已设为' : '已取消'}人事专员：${data.updated || 0} 人`, 'ok'));
        await loadAdminUsers(false);
      } catch (err) {
        setText('userBulkStatus', String(err.message || err), true);
      }
    }
    function leavePlatform() { return val('leavePlatform') || params.get('platform') || 'wecom'; }
    async function loadLeaveRealtimeStatus() {
      try {
        const data = await api(`/api/v1/admin/leave/realtime-sync?platform=${encodeURIComponent(leavePlatform())}`);
        const policies = data.policies || [];
        const syncLogs = data.recent_sync_logs || data.logs || [];
        const holds = data.pending_holds || [];
        const rows = policies.map((p) => `<tr><td>${safe(p.vacation_id)}</td><td>${safe(p.vacation_name || '-')}</td><td>${safe(p.leave_kind || '-')}</td><td>${safe(p.advance_seconds || 0)}</td><td>${p.overtime_credit ? chip('可冲抵','ok') : chip('否')}</td></tr>`);
        setHtml('leaveRealtimeStatus',
          chip(`假期类型 ${policies.length}`) +
          chip(`审批中占用 ${holds.length || 0}`) +
          `<h3>假期类型</h3>${table(['ID','名称','类型','允许预支秒数','加班冲抵'], rows)}` +
          `<h3>最近同步</h3><pre>${safe(JSON.stringify(syncLogs.slice(0, 5), null, 2))}</pre>`
        );
      } catch (err) {
        setText('leaveRealtimeStatus', String(err.message || err), true);
      }
    }
    async function syncLeavePolicies() {
      try {
        const data = await api(`/api/v1/admin/leave/policies/sync?platform=${encodeURIComponent(leavePlatform())}`, {method:'POST'});
        setHtml('leaveRealtimeStatus', chip(`已同步 ${safe(data.synced || 0)} 个假期类型`, 'ok') + `<pre>${safe(JSON.stringify(data, null, 2))}</pre>`);
        await loadLeaveRealtimeStatus();
      } catch (err) {
        setText('leaveRealtimeStatus', String(err.message || err), true);
      }
    }
    async function runLeaveRealtimeSync() {
      try {
        const data = await api(`/api/v1/admin/leave/realtime-sync/run?platform=${encodeURIComponent(leavePlatform())}`, {method:'POST'});
        setHtml('leaveRealtimeStatus', chip(`已处理 ${safe(data.processed || 0)} 条`, 'ok') + `<pre>${safe(JSON.stringify(data, null, 2))}</pre>`);
      } catch (err) {
        setText('leaveRealtimeStatus', String(err.message || err), true);
      }
    }
    async function loadLeaveFormNotice() {
      try {
        const userId = val('leaveNoticeUserId') || val('leaveBalanceUserId');
        if (!userId) throw new Error('请先填写员工用户 ID');
        const data = await api(`/api/v1/admin/leave/form-notice?platform=${encodeURIComponent(leavePlatform())}&user_id=${encodeURIComponent(userId)}`);
        setText('leaveFormNotice', data.notice || '暂无动态提示');
      } catch (err) {
        setText('leaveFormNotice', String(err.message || err), true);
      }
    }
    async function applyLeaveBalanceTarget() {
      try {
        const payload = {
          platform: leavePlatform(),
          user_id: val('leaveBalanceUserId'),
          vacation_id: Number(val('leaveVacationId') || 0),
          vacation_name: val('leaveVacationName'),
          target_leftduration: Number(val('leaveTargetDuration') || 0),
          time_attr: Number(val('leaveTimeAttr') || 1),
          reason: val('leaveAdjustReason'),
          allow_local_negative: !!el('leaveAllowNegative').checked
        };
        if (!payload.user_id) throw new Error('请填写员工用户 ID');
        if (!payload.vacation_id) throw new Error('请填写假期类型 ID');
        if (!payload.reason) throw new Error('请填写调整原因');
        const data = await api('/api/v1/admin/leave/balance-target', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
        setHtml('leaveAdjustResult', chip('额度调整已保存', 'ok') + `<pre>${safe(JSON.stringify(data.result || data, null, 2))}</pre>`);
      } catch (err) {
        setText('leaveAdjustResult', String(err.message || err), true);
      }
    }
    async function runLeaveNegativeProbe() {
      try {
        const payload = {
          platform: leavePlatform(),
          user_id: val('leaveProbeUserId'),
          vacation_id: Number(val('leaveProbeVacationId') || 0),
          negative_duration: Number(val('leaveProbeDuration') || -86400),
          confirm_live_write: !!el('leaveProbeLive').checked
        };
        if (!payload.user_id) throw new Error('请填写测试员工用户 ID');
        if (!payload.vacation_id) throw new Error('请填写假期类型 ID');
        const data = await api('/api/v1/admin/leave/negative-probe', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
        setHtml('leaveProbeResult', chip('验证已完成', 'ok') + `<pre>${safe(JSON.stringify(data.result || data, null, 2))}</pre>`);
      } catch (err) {
        setText('leaveProbeResult', String(err.message || err), true);
      }
    }
    async function loadLeaveNegativeProbeResults() {
      try {
        const data = await api(`/api/v1/admin/leave/negative-probe?platform=${encodeURIComponent(leavePlatform())}`);
        const rows = (data.results || []).map((r) => `<tr><td>${safe(r.created_at || '-')}</td><td>${safe(r.user_id)}</td><td>${safe(r.vacation_name || r.vacation_id)}</td><td>${safe(r.negative_duration)}</td><td>${r.negative_supported ? chip('支持','ok') : chip('不支持/未验证','warn')}</td><td>${safe(r.error || '-')}</td></tr>`);
        setHtml('leaveProbeResult', table(['时间','员工','假期','测试值','企微负数','错误'], rows));
      } catch (err) {
        setText('leaveProbeResult', String(err.message || err), true);
      }
    }
    function leaveWorkflowPayload(apply) {
      return {
        template_id: val('leaveWorkflowTemplateId'),
        notice_text: val('leaveWorkflowNoticeText') || '【假期额度说明】本页显示的是企微可申请额度；真实余额、欠假和加班调休冲抵情况以企业 AI 助手动态提示和人事后台台账为准。提交请假前如不确定，请先在企业 AI 助手中发送“我要请假”查询。',
        apply_update: !!apply
      };
    }
    async function planLeaveWorkflowNotice() {
      try {
        const data = await api('/api/v1/admin/leave/workflow-notice', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(leaveWorkflowPayload(false))});
        setHtml('leaveWorkflowNoticeResult', chip('已生成更新预览', 'ok') + `<pre>${safe(JSON.stringify(data.result || data, null, 2))}</pre>`);
      } catch (err) {
        setText('leaveWorkflowNoticeResult', String(err.message || err), true);
      }
    }
    async function applyLeaveWorkflowNotice() {
      try {
        const data = await api('/api/v1/admin/leave/workflow-notice', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(leaveWorkflowPayload(true))});
        setHtml('leaveWorkflowNoticeResult', chip('模板说明写入流程已执行', 'ok') + `<pre>${safe(JSON.stringify(data.result || data, null, 2))}</pre>`);
      } catch (err) {
        setText('leaveWorkflowNoticeResult', String(err.message || err), true);
      }
    }
    function mailPayload() {
      const encryption = val('mailEncryption');
      if (!encryption) throw new Error('请选择邮箱服务商要求的连接加密方式');
      return {
        account_id: val('mailAccountId'),
        account_label: val('mailAccountLabel'),
        platform: val('mailPlatform') || 'wecom',
        user_id: val('mailUserId'),
        user_name: val('mailUserName'),
        email_address: val('mailEmailAddress'),
        protocol: val('mailProtocol') || 'imap',
        imap_host: val('mailImapHost'),
        imap_port: Number(val('mailImapPort') || 993),
        encryption,
        imap_ssl: encryption === 'ssl_tls',
        username: val('mailUsername') || val('mailEmailAddress'),
        password: val('mailPassword'),
        folder: val('mailFolder') || 'INBOX',
        poll_interval_minutes: Number(val('mailPollInterval') || 1),
        enabled: !!el('mailEnabled').checked
      };
    }
    function applyMailAccount(account) {
      el('mailPlatform').value = account.platform || 'wecom';
      el('mailAccountId').value = account.account_id || '';
      el('mailAccountLabel').value = account.account_label || '';
      el('mailUserId').value = account.user_id || '';
      el('mailUserName').value = account.user_name || '';
      el('mailEmailAddress').value = account.email_address || '';
      el('mailProtocol').value = account.protocol || 'imap';
      el('mailImapHost').value = account.imap_host || '';
      el('mailImapPort').value = account.imap_port || 993;
      el('mailUsername').value = account.username || account.email_address || '';
      el('mailPassword').value = '';
      el('mailFolder').value = account.folder || 'INBOX';
      el('mailPollInterval').value = account.poll_interval_minutes || 1;
      el('mailEncryption').value = account.encryption || (account.imap_ssl === false ? 'none' : 'ssl_tls');
      el('mailEnabled').checked = account.enabled !== false;
      setHtml('mailAccountResult', chip(`已加载 ${safe(account.user_id)} 的 ${safe(account.account_label || account.email_address || '邮箱')} 配置`, 'ok'));
    }
    function newMailAccount() {
      el('mailAccountId').value = '';
      el('mailAccountLabel').value = '';
      el('mailEmailAddress').value = '';
      el('mailProtocol').value = 'imap';
      el('mailImapHost').value = '';
      el('mailImapPort').value = 993;
      el('mailEncryption').value = '';
      el('mailUsername').value = '';
      el('mailPassword').value = '';
      el('mailFolder').value = 'INBOX';
      el('mailPollInterval').value = 1;
      el('mailEnabled').checked = true;
      setHtml('mailAccountResult', chip('已切换为新增邮箱模式：员工姓名/ID 保留，保存时会新增一个邮箱，不会覆盖右侧已配置邮箱。', 'ok'));
    }
    async function inferMailAccount() {
      try {
        const payload = {
          platform: val('mailPlatform') || 'wecom',
          user_id: val('mailUserId'),
          user_name: val('mailUserName'),
          email_address: val('mailEmailAddress')
        };
        const data = await api('/api/v1/admin/mail/accounts/infer', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
        const account = data.account || {};
        applyMailAccount({...account, account_id: val('mailAccountId')});
        el('mailPassword').value = '';
        setHtml('mailAccountResult', chip('已自动匹配邮箱配置', 'ok') + `<p>${safe(account.source || '')}</p><p>请填写密码/授权码后点击“保存并测试邮箱”。</p>`);
      } catch (err) {
        setText('mailAccountResult', String(err.message || err), true);
      }
    }
    window.mailAccountRows = [];
    function applyMailAccountByIndex(index) {
      const account = window.mailAccountRows[Number(index)];
      if (!account) throw new Error('未找到已配置邮箱，请先刷新列表');
      applyMailAccount(account);
    }
    function mailAccountTable(rows) {
      const empty = '<tr><td colspan="8">暂无邮箱配置</td></tr>';
      return `<div class="table-wrap"><table class="mail-table"><colgroup><col style="width:76px"><col style="width:130px"><col style="width:120px"><col style="width:220px"><col style="width:82px"><col style="width:180px"><col style="width:130px"><col style="width:140px"></colgroup><thead><tr><th>平台</th><th>员工</th><th>用途</th><th>邮箱</th><th>协议</th><th>服务器</th><th>状态</th><th>操作</th></tr></thead><tbody>${rows.length ? rows.join('') : empty}</tbody></table></div>`;
    }
    async function loadMailAccounts() {
      try {
        const platform = val('mailPlatform') || params.get('platform') || 'wecom';
        const data = await api(`/api/v1/admin/mail/accounts?platform=${encodeURIComponent(platform)}`);
        window.mailAccountRows = Array.isArray(data.accounts) ? data.accounts : [];
        const rows = window.mailAccountRows.map((account, index) => {
          const status = `<div class="status-pills">${account.enabled ? chip('启用','ok') : chip('停用','warn')}${account.password_configured ? chip('密码已配置','ok') : chip('缺少密码','bad')}</div>`;
          const actions = `<div class="row-actions"><button class="secondary" onclick="applyMailAccountByIndex(${index})">编辑</button><button class="secondary" onclick="testMailAccount(${jsAttr(account.platform)},${jsAttr(account.user_id)},${jsAttr(account.account_id)})">测试</button><button class="tonal" onclick="setMailAccountEnabled(${jsAttr(account.platform)},${jsAttr(account.user_id)},${account.enabled ? 'false' : 'true'},${jsAttr(account.account_id)})">${account.enabled ? '停用' : '启用'}</button><button class="danger" onclick="deleteMailAccount(${jsAttr(account.platform)},${jsAttr(account.user_id)},${jsAttr(account.account_id)})">删除</button></div>`;
          const employee = account.user_name ? `<div class="cell-primary">${safe(account.user_name)}</div><div class="cell-secondary">${safe(account.user_id)}</div>` : `<div class="cell-primary">${safe(account.user_id)}</div>`;
          const label = safe(account.account_label || '默认邮箱');
          const email = `<span class="mono-wrap" title="${safe(account.email_address)}">${safe(account.email_address)}</span>`;
          const server = `<span class="mono-wrap" title="${safe(account.imap_host)}:${safe(account.imap_port)}">${safe(account.imap_host)}:${safe(account.imap_port)}</span><div class="cell-secondary">${safe(account.encryption || 'ssl_tls')}</div>`;
          return `<tr><td>${chip(account.platform || 'wecom')}</td><td>${employee}</td><td>${label}</td><td>${email}</td><td><span class="protocol-pill">${safe(account.protocol || 'imap')}</span></td><td>${server}</td><td>${status}</td><td>${actions}</td></tr>`;
        });
        setHtml('mailAccountList', mailAccountTable(rows));
        setHtml('mailAccountResult', chip(`已加载 ${window.mailAccountRows.length} 条邮箱配置`, window.mailAccountRows.length ? 'ok' : 'warn'));
      } catch (err) {
        setText('mailAccountResult', String(err.message || err), true);
      }
    }
    async function saveMailAccount() {
      try {
        const data = await api('/api/v1/admin/mail/accounts', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(mailPayload())});
        const account = data.account || {};
        setHtml('mailAccountResult', chip(`已保存 ${safe(account.user_id || '')} 邮箱配置，正在真实读取测试`, 'ok'));
        el('mailPassword').value = '';
        await loadMailAccounts();
        el('mailAccountId').value = account.account_id || '';
        await testMailAccount(account.platform, account.user_id, account.account_id);
      } catch (err) {
        setText('mailAccountResult', String(err.message || err), true);
      }
    }
    async function setMailAccountEnabled(platform, userId, enabled, accountId) {
      try {
        await api('/api/v1/admin/mail/accounts/status', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({platform, user_id:userId, account_id:accountId || '', enabled})});
        await loadMailAccounts();
      } catch (err) {
        setText('mailAccountResult', String(err.message || err), true);
      }
    }
    async function testMailAccount(platform, userId, accountId) {
      try {
        if (!(platform && userId) && !val('mailAccountId')) {
          throw new Error('请先在右侧“已配置邮箱”选择一条邮箱，或点击“保存并测试邮箱”保存当前新增邮箱；为避免误测多个邮箱，这里不再默认测试该员工全部邮箱。');
        }
        const payload = platform && userId
          ? {platform, user_id:userId, account_id:accountId || ''}
          : {platform: val('mailPlatform') || 'wecom', user_id: val('mailUserId'), user_name: val('mailUserName'), account_id: val('mailAccountId')};
        const data = await api('/api/v1/admin/mail/accounts/test', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
        const target = data.account_source || data.user_id || '';
        const outcome = data.ok ? chip(`读取测试成功：${safe(target)}`, 'ok') : chip(`读取测试失败：${safe(target)}`, 'bad');
        setHtml('mailAccountResult', `${outcome}<pre>${safe(data.result || '')}</pre>`);
      } catch (err) {
        setText('mailAccountResult', String(err.message || err), true);
      }
    }
    async function deleteMailAccount(platform, userId, accountId) {
      try {
        platform = platform || val('mailPlatform') || 'wecom';
        userId = userId || val('mailUserId');
        accountId = accountId || val('mailAccountId');
        if (!userId && !accountId) throw new Error('缺少员工用户 ID 或邮箱配置 ID');
        if (!confirm(`确认删除 ${userId || ''} 的这个邮箱配置？`)) return;
        const suffix = accountId ? `?account_id=${encodeURIComponent(accountId)}` : '';
        await api(`/api/v1/admin/mail/accounts/${encodeURIComponent(platform)}/${encodeURIComponent(userId || '-')}${suffix}`, {method:'DELETE'});
        setHtml('mailAccountResult', chip(`已删除 ${safe(userId || accountId)} 邮箱配置`, 'warn'));
        el('mailAccountId').value = '';
        await loadMailAccounts();
      } catch (err) {
        setText('mailAccountResult', String(err.message || err), true);
      }
    }
    const publicSourceTemplates = {
      flight: {
        label:'航班查询',
        source:'OpenSky 免费态势数据 / 企业差旅或航班聚合 API',
        url:'',
        method:'GET',
        type:'json',
        headers:{},
        params:{},
        body:{},
        fields:['data.0.flight_no:航班号','data.0.departure_time:起飞时间','data.0.arrival_time:到达时间','data.0.status:状态'],
        notes:'OpenSky 免费源只适合飞行态势，不提供城市到城市班期/余票。企业如需“明天去北京有哪些航班”，建议接差旅平台、航司、机场或 Aviationstack/AirLabs/FlightAware 等授权 API；未配置时系统会使用联网检索兜底。'
      },
      shipment: {
        label:'货运/运单查询',
        source:'Karrio 自托管 / 承运商官方 API',
        url:'',
        method:'GET',
        type:'json',
        headers:{Authorization:'Bearer {secret}'},
        params:{tracking_no:'{tracking_no}', carrier:'{carrier}'},
        body:{},
        fields:['tracking_number:运单号','status:状态','events.0.description:最新轨迹','events.0.date:更新时间'],
        notes:'Karrio 可自托管作为统一物流接口，但真实轨迹仍取决于承运商凭据。未配置时系统会使用联网检索兜底。'
      },
      supply_price: {
        label:'供应链价格',
        source:'金属价格 API / 交易所授权行情 / 企业采购价格库',
        url:'',
        method:'GET',
        type:'json',
        headers:{Authorization:'Bearer {secret}'},
        params:{symbol:'{symbol}', query:'{query}'},
        body:{},
        fields:['symbol:品种','price:价格','currency:币种','date:日期'],
        notes:'镍、铬等金属价格没有稳定无 key 商用权威 API。可配置 Metals-API、Metals.Dev、交易所授权行情或企业内部采购价格库；未配置时系统会使用联网检索兜底。'
      },
      fred: {
        label:'宏观指标',
        source:'FRED',
        url:'',
        method:'GET',
        type:'json',
        headers:{},
        params:{},
        body:{},
        fields:['observations.0.date:日期','observations.0.value:数值'],
        notes:'FRED 需要免费 API Key。也可继续使用服务器环境变量 FRED_API_KEY。'
      }
    };
    function parseJsonField(id, fallback) {
      const raw = val(id).trim();
      if (!raw) return fallback;
      return JSON.parse(raw);
    }
    function publicSourcePayload() {
      return {
        kind: val('publicSourceKind'),
        label: val('publicSourceLabel'),
        source: val('publicSourceName'),
        url: val('publicSourceUrl'),
        method: val('publicSourceMethod') || 'GET',
        type: val('publicSourceType') || 'json',
        secret: val('publicSourceSecret'),
        headers: parseJsonField('publicSourceHeaders', {}),
        params: parseJsonField('publicSourceParams', {}),
        body: parseJsonField('publicSourceBody', {}),
        fields: val('publicSourceFields').split(/\\n+/).map(s => s.trim()).filter(Boolean),
        notes: val('publicSourceNotes'),
        enabled: !!el('publicSourceEnabled').checked
      };
    }
    function applyPublicSourceConfig(source) {
      const template = publicSourceTemplates[source.kind] || {};
      el('publicSourceKind').value = source.kind || 'flight';
      el('publicSourceLabel').value = source.label || template.label || '';
      el('publicSourceName').value = source.source || template.source || '';
      el('publicSourceUrl').value = source.url || template.url || '';
      el('publicSourceMethod').value = source.method || template.method || 'GET';
      el('publicSourceType').value = source.type || template.type || 'json';
      el('publicSourceSecret').value = '';
      el('publicSourceHeaders').value = JSON.stringify(source.headers || template.headers || {}, null, 2);
      el('publicSourceParams').value = JSON.stringify(source.params || template.params || {}, null, 2);
      el('publicSourceBody').value = JSON.stringify(source.body || template.body || {}, null, 2);
      el('publicSourceFields').value = (source.fields || template.fields || []).join('\\n');
      el('publicSourceNotes').value = source.notes || template.notes || '';
      el('publicSourceEnabled').checked = source.enabled !== false;
      setHtml('publicDataSourceResult', chip(`已加载 ${safe(source.label || source.kind)} 配置`, 'ok'));
    }
    function applyPublicSourceTemplate() {
      const kind = val('publicSourceKind') || 'flight';
      applyPublicSourceConfig({kind, ...(publicSourceTemplates[kind] || {})});
    }
    async function loadPublicDataSources() {
      try {
        const data = await api('/api/v1/admin/public-data/sources');
        window.publicDataSourceRows = data.sources || [];
        const rows = window.publicDataSourceRows.map((source, index) => {
          const status = source.builtin ? chip('内置免费源','ok') : (source.configured ? chip('已配置','ok') : chip('需配置/检索兜底','warn'));
          const enabled = source.enabled ? chip('启用','ok') : chip('停用','warn');
          const secret = source.secret_configured ? chip('密钥已配置','ok') : '';
          const tested = source.last_test_at ? (source.last_test_ok ? chip('最近测试成功','ok') : chip('最近测试失败','bad')) : '';
          const actions = `<button class="secondary" onclick="applyPublicSourceConfig(window.publicDataSourceRows[${index}])">编辑</button> <button class="secondary" onclick="testPublicDataSource(${jsAttr(source.kind)})">测试</button>`;
          return `<tr><td>${safe(source.label || source.kind)}<br><span class="chip">${safe(source.kind)}</span></td><td>${safe(source.source || '')}</td><td>${status}${enabled}${secret}${tested}</td><td>${safe(source.notes || '')}</td><td>${actions}</td></tr>`;
        });
        setHtml('publicDataSourceList', table(['数据源','来源','状态','备注','操作'], rows));
        setHtml('publicDataSourceResult', chip(`已加载 ${window.publicDataSourceRows.length} 个数据源`, 'ok'));
      } catch (err) {
        setText('publicDataSourceResult', String(err.message || err), true);
      }
    }
    async function savePublicDataSource() {
      try {
        const data = await api('/api/v1/admin/public-data/sources', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(publicSourcePayload())});
        setHtml('publicDataSourceResult', chip(`已保存 ${safe((data.source || {}).label || val('publicSourceKind'))}`, 'ok'));
        el('publicSourceSecret').value = '';
        await loadPublicDataSources();
      } catch (err) {
        setText('publicDataSourceResult', String(err.message || err), true);
      }
    }
    async function testPublicDataSource(kind) {
      try {
        const testKind = kind || val('publicSourceKind') || 'flight';
        const query = prompt('请输入测试问题或关键词', testKind === 'flight' ? '明天去北京的航班' : (testKind === 'supply_price' ? '镍价格' : '测试')) || '';
        const data = await api('/api/v1/admin/public-data/sources/test', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({kind:testKind, query})});
        const status = data.ok ? chip(`测试成功，耗时 ${data.elapsed_ms}ms`, 'ok') : chip(`测试未通过，耗时 ${data.elapsed_ms}ms`, 'bad');
        setHtml('publicDataSourceResult', `${status}<pre>${safe(data.result || '')}</pre>`);
        await loadPublicDataSources();
      } catch (err) {
        setText('publicDataSourceResult', String(err.message || err), true);
      }
    }
    async function deletePublicDataSource() {
      try {
        const kind = val('publicSourceKind');
        if (!kind) throw new Error('请选择数据源类型');
        if (!confirm(`确认删除 ${kind} 的外部配置？内置源不会被删除；未配置时会继续使用内置能力或联网检索兜底。`)) return;
        await api(`/api/v1/admin/public-data/sources/${encodeURIComponent(kind)}`, {method:'DELETE'});
        setHtml('publicDataSourceResult', chip(`已删除 ${safe(kind)} 外部配置`, 'warn'));
        await loadPublicDataSources();
      } catch (err) {
        setText('publicDataSourceResult', String(err.message || err), true);
      }
    }
    async function loadModels() {
      try {
        const data = await api('/api/v1/admin/models');
        const rows = (data.profiles || []).map((profile) => {
          const status = `${profile.is_default ? chip('默认', 'ok') : ''}${profile.enabled ? chip('启用','ok') : chip('停用','warn')}${profile.api_key_configured ? '' : chip('API Key缺失','bad')}`;
          const defaultBtn = profile.is_default
            ? `<button class="tonal" disabled>默认</button>`
            : `<button class="tonal" onclick="setDefaultModel(${jsAttr(profile.profile_id)})">默认</button>`;
          const actions = `<button class="secondary" onclick="applyProfileToForm(${jsAttr(profile.profile_id)},${jsAttr(profile.provider)},${jsAttr(((profile.metadata||{}).sdk_format || profile.provider))},${jsAttr(profile.api_base || '')},${jsAttr(profile.model_name)},${jsAttr(String(profile.max_tokens || 4096))})">编辑</button> ${defaultBtn} <button class="danger" onclick="deleteModelProfile(${jsAttr(profile.profile_id)})">删除</button>`;
          return `<tr><td>${safe(profile.profile_id)}</td><td>${safe(profile.model_name)}</td><td>${status}</td><td>${actions}</td></tr>`;
        });
        setHtml('modelProfiles', table(['配置','模型','状态','操作'], rows));
      } catch (err) {
        setText('modelActionStatus', String(err.message || err), true);
      }
    }
    async function discoverModels() {
      try {
        const payload = {provider: val('modelProvider'), sdk_format: val('modelSdkFormat'), api_base: val('modelApiBase'), api_key: val('modelApiKey')};
        const data = await api('/api/v1/admin/models/discover', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
        const rows = (data.models || []).map((model) => `<tr><td>${safe(model.id)}</td><td>${safe(model.name)}</td><td><button class="secondary" onclick="chooseModel(${jsAttr(model.id)},${jsAttr(model.name || model.id)})">选择</button></td></tr>`);
        setHtml('modelDiscovery', `<p>${safe(data.message || '')}</p>` + table(['模型 ID','名称','操作'], rows));
      } catch (err) {
        setText('modelActionStatus', String(err.message || err), true);
      }
    }
    function modelProfileSlug(modelId) {
      return String(modelId || 'model').toLowerCase().replace(/^opencode[/]/, 'opencode-').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 64) || 'model';
    }
    function chooseModel(modelId, modelName='') {
      el('modelName').value = modelId;
      if (!val('modelProfileId')) el('modelProfileId').value = modelProfileSlug(modelId);
      setHtml('modelActionStatus', chip(`已选择 ${safe(modelName || modelId)}，已自动填入模型 ID 和配置名称；“单次最大输出 Token（本地上限）”请按服务商文档手工确认后保存`, 'ok'));
    }
    function applyProfileToForm(profileId, provider, sdkFormat, apiBase, modelName, maxTokens) {
      el('modelProfileId').value = profileId || '';
      el('modelProvider').value = provider || 'openai_compatible';
      el('modelSdkFormat').value = sdkFormat || 'openai';
      el('modelApiBase').value = apiBase || '';
      el('modelName').value = modelName || '';
      el('modelMaxTokens').value = maxTokens || '4096';
      setHtml('modelActionStatus', chip(`已加载配置 ${safe(profileId)} 到表单，可修改后保存`, 'ok'));
    }
    async function setDefaultModel(profileId) {
      try {
        const data = await api('/api/v1/admin/models/default', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({profile_id: profileId})});
        setHtml('modelActionStatus', chip(`已将 ${safe(data.profile_id)} 设为默认模型`, 'ok'));
        await loadModels();
      } catch (err) {
        setText('modelActionStatus', String(err.message || err), true);
      }
    }
    async function deleteModelProfile(profileId) {
      try {
        if (!profileId) throw new Error('缺少模型配置名称');
        if (!confirm(`确认删除模型配置 ${profileId}？删除后不会影响服务商账号，但该配置将不能再被选择。`)) return;
        const data = await api(`/api/v1/admin/models/${encodeURIComponent(profileId)}`, {method:'DELETE'});
        setHtml('modelActionStatus', chip(`已删除模型配置 ${safe(data.profile_id)}`, 'warn'));
        await loadModels();
      } catch (err) {
        setText('modelActionStatus', String(err.message || err), true);
      }
    }
    async function saveModelProfile() {
      try {
        const payload = {
          profile_id: val('modelProfileId'),
          provider: val('modelProvider'),
          sdk_format: val('modelSdkFormat'),
          api_base: val('modelApiBase'),
          api_key: val('modelApiKey'),
          model_name: val('modelName'),
          max_tokens: Number(val('modelMaxTokens') || 4096),
          enabled: true
        };
        const data = await api('/api/v1/admin/models', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
        setHtml('modelActionStatus', chip(`已保存 ${((data.profile || {}).profile_id) || payload.profile_id}`, 'ok'));
        await loadModels();
      } catch (err) {
        setText('modelActionStatus', String(err.message || err), true);
      }
    }
    async function searchEmployeeByName() {
      try {
        const name = val('employeeName');
        if (!name) throw new Error('请先填写员工姓名');
        const platform = val('employeePlatform') || 'wecom';
        const data = await api(`/api/v1/admin/users?platform=${encodeURIComponent(platform)}&search=${encodeURIComponent(name)}`);
        const matches = (data.users || []).filter(u => (u.name || '').includes(name) || (u.user_id || '').toLowerCase().includes(name.toLowerCase()));
        if (!matches.length) { setHtml('employeeResult', '未找到匹配员工'); return; }
        if (matches.length === 1) {
          el('employeeUserId').value = matches[0].user_id;
          el('employeeBotName').value = matches[0].name || matches[0].user_id;
          setHtml('employeeResult', chip(`已选择：${safe(matches[0].name)} (${safe(matches[0].user_id)})`, 'ok'));
        } else {
          const rows = matches.map(u => `<tr><td><button class="secondary" onclick="selectEmployee(${jsAttr(u.user_id)},${jsAttr(u.name||u.user_id)})">选择</button></td><td>${safe(u.name||'-')}</td><td>${safe(u.user_id)}</td><td>${safe(u.department_path||'-')}</td></tr>`);
          setHtml('employeeResult', '<p>找到多个匹配：</p>'+table(['操作','姓名','用户ID','部门'], rows));
        }
      } catch (err) { setText('employeeResult', String(err.message || err), true); }
    }
    function selectEmployee(userId, name) {
      el('employeeUserId').value = userId;
      el('employeeBotName').value = defaultEmployeeBotName(val('employeePlatform') || 'wecom');
      setHtml('employeeResult', chip(`已选择：${name}`, 'ok'));
    }
    async function sendEmployeeWelcome(platform, userId, displayName) {
      try {
        const payload = {platform, user_id:userId, display_name:displayName || defaultEmployeeBotName(platform), notify:true};
        const data = await api('/api/v1/admin/employee-bots/welcome', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
        setHtml('employeeResult', chip(`已发送欢迎：${safe((data.assignment || {}).user_id || userId)}`, 'ok') + chip(`通知：${safe(data.notify_status || '-')}`));
        await loadEmployeeBots();
        await loadAdminUsers(false);
      } catch (err) {
        setText('employeeResult', String(err.message || err), true);
      }
    }
    async function activateEmployeeBot() {
      try {
        const payload = {
          platform: val('employeePlatform') || 'wecom',
          user_id: val('employeeUserId'),
          display_name: val('employeeBotName') || '企业 AI 助手',
          notify: true
        };
        if (!payload.user_id) throw new Error('请先填写员工的企业 IM 用户 ID');
        const data = await api('/api/v1/admin/employee-bots/activate', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
        setHtml('employeeResult', chip('员工 AI 助手已开通','ok') + chip(`通知：${((data.assignment || {}).notify_status) || '-'}`));
        await loadEmployeeBots();
      } catch (err) {
        setText('employeeResult', String(err.message || err), true);
      }
    }
    async function deactivateEmployeeBot() {
      try {
        const payload = {platform: val('employeePlatform') || 'wecom', user_id: val('employeeUserId')};
        if (!payload.user_id) throw new Error('请先填写员工的企业 IM 用户 ID');
        const data = await api('/api/v1/admin/employee-bots/deactivate', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
        setHtml('employeeResult', chip(`状态：${((data.assignment || {}).status) || '已停用'}`, 'warn'));
        await loadEmployeeBots();
      } catch (err) {
        setText('employeeResult', String(err.message || err), true);
      }
    }
    async function broadcastOrganization() {
      try {
        const payload = {
          platform: val('broadcastPlatform') || 'wecom',
          target: val('broadcastTarget'),
          message: val('broadcastMessage')
        };
        if (!payload.target) throw new Error('请填写组织范围，例如：全体员工、技术部或部门 ID');
        if (!payload.message) throw new Error('请填写通知内容');
        const data = await api('/api/v1/admin/organization/broadcast', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
        const status = data.ok ? chip('发送完成', 'ok') : chip('部分失败', 'warn');
        setHtml('broadcastResult',
          status +
          chip(`已发送 ${safe(data.sent || 0)} 人`, 'ok') +
          chip(`跳过 ${safe(data.skipped || 0)} 人`) +
          (data.failed ? chip(`失败 ${safe(data.failed)} 人`, 'bad') : '') +
          `<div class="muted">目标：${safe(payload.target)}；匹配通讯录人数：${safe(data.matched || 0)}；符合发送条件：${safe(data.eligible || 0)}</div>`
        );
      } catch (err) {
        setText('broadcastResult', String(err.message || err), true);
      }
    }
    async function loadRateminStatus() {
      try {
        loadRateminChannelStatus(false);
        const data = await api('/api/v1/admin/ratemin/status');
        const eventRows = (data.events || []).map((item) => `<tr><td>${safe(item.source_db)}</td><td>${safe(item.delivery_status || '-')}</td><td>${safe(item.c || 0)}</td></tr>`);
        const bindingRows = (data.bindings || []).map((item) => `<tr><td>${safe(item.source_db)}</td><td>${safe(item.status || '-')}</td><td>${safe(item.match_method || '-')}</td><td>${safe(item.c || 0)}</td></tr>`);
        const snapshotRows = (data.user_snapshots || []).map((item) => `<tr><td>${safe(item.source_db)}</td><td>${safe(item.c || 0)}</td></tr>`);
        setHtml('rateminStatus',
          '<h3>通知事件</h3>' + table(['数据库','发送状态','数量'], eventRows) +
          '<h3>账号绑定</h3>' + table(['数据库','绑定状态','匹配方式','数量'], bindingRows) +
          '<h3>业务系统目录</h3>' + table(['数据库','已同步人数'], snapshotRows)
        );
      } catch (err) {
        setText('rateminStatus', String(err.message || err), true);
      }
    }
    async function loadRateminDirectory() {
      try {
        const query = val('rateminDirectoryQuery');
        const sourceDb = val('rateminDirectorySourceDb');
        const limit = Math.max(20, Math.min(2000, Number(val('rateminDirectoryLimit') || 500)));
        const url = '/api/v1/admin/ratemin/directory'
          + `?platform=${encodeURIComponent(params.get('platform') || 'wecom')}`
          + `&source_db=${encodeURIComponent(sourceDb)}`
          + `&query=${encodeURIComponent(query)}`
          + `&sort=${encodeURIComponent(rateminDirectoryState.sort)}`
          + `&direction=${encodeURIComponent(rateminDirectoryState.direction)}`
          + `&limit=${encodeURIComponent(String(limit))}`;
        const data = await api(url);
        const entries = data.entries || [];
        const bound = entries.filter((item) => item.directory_status === 'bound').length;
        const summary = `<p class="muted">当前显示 ${safe(entries.length)} 人；已绑定 ${safe(bound)} 人；未绑定 ${safe(entries.length - bound)} 人；排序：${safe(rateminDirectoryState.sort)} ${safe(rateminDirectoryState.direction === 'asc' ? '升序' : '降序')}</p>`;
        setHtml('rateminBindings', summary + renderRateminDirectoryTable(entries));
      } catch (err) {
        setText('rateminBindings', String(err.message || err), true);
      }
    }
    async function autoBindAllRatemin() {
      try {
        const data = await api(`/api/v1/admin/ratemin/auto-bind?platform=${encodeURIComponent(params.get('platform') || 'wecom')}`, {method:'POST'});
        setHtml('rateminBindResult',
          chip(`已扫描 ${safe(data.scanned || 0)} 人`, 'ok') +
          chip(`新绑定 ${safe(data.bound || 0)} 人`, 'ok') +
          chip(`已跳过 ${safe(data.skipped || 0)} 人`) +
          chip(`重名 ${safe(data.ambiguous || 0)} 人`, 'warn') +
          chip(`未匹配 ${safe(data.unmatched || 0)} 人`, 'warn')
        );
        await loadRateminStatus();
        await loadRateminDirectory();
      } catch (err) {
        setText('rateminBindResult', String(err.message || err), true);
      }
    }
    function fillRateminBinding(sourceDb, operId, loginName, displayName, imUserId, imDisplayName) {
      el('rateminSourceDb').value = sourceDb || 'business_a';
      el('rateminOperId').value = operId || '';
      el('rateminLoginName').value = loginName || '';
      el('rateminDisplayName').value = displayName || '';
      el('rateminImUserId').value = imUserId || '';
      el('rateminImDisplayName').value = imDisplayName || '';
      setHtml('rateminBindResult', chip('已填入绑定信息，可修改后保存', 'ok'));
    }
    async function saveRateminBinding() {
      try {
        const payload = {
          source_db: val('rateminSourceDb'),
          rate_oper_id: val('rateminOperId'),
          rate_login_name: val('rateminLoginName'),
          rate_display_name: val('rateminDisplayName'),
          platform: params.get('platform') || 'wecom',
          im_user_id: val('rateminImUserId'),
          im_display_name: val('rateminImDisplayName')
        };
        if (!payload.source_db || !payload.rate_oper_id || !payload.im_user_id) throw new Error('请填写业务系统数据库、OperID 和企微 user_id');
        const data = await api('/api/v1/admin/ratemin/bindings', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
        setHtml('rateminBindResult', chip(`已绑定：${safe(data.rate_display_name || data.rate_oper_id)} -> ${safe(data.im_display_name || data.im_user_id)}`, 'ok'));
        await loadRateminDirectory();
        await loadRateminStatus();
      } catch (err) {
        setText('rateminBindResult', String(err.message || err), true);
      }
    }
    async function removeRateminBinding() {
      try {
        const sourceDb = val('rateminSourceDb');
        const operId = val('rateminOperId');
        if (!sourceDb || !operId) throw new Error('请填写业务系统数据库和 OperID');
        const data = await api(`/api/v1/admin/ratemin/bindings?source_db=${encodeURIComponent(sourceDb)}&rate_oper_id=${encodeURIComponent(operId)}&platform=${encodeURIComponent(params.get('platform') || 'wecom')}`, {method:'DELETE'});
        setHtml('rateminBindResult', chip(`已解除绑定：${safe(data.source_db)} / ${safe(data.rate_oper_id)}`, 'warn'));
        await loadRateminDirectory();
        await loadRateminStatus();
      } catch (err) {
        setText('rateminBindResult', String(err.message || err), true);
      }
    }
    async function importGuides() {
      try {
        const data = await api('/api/v1/admin/knowledge/import/company-guides', {method:'POST'});
        setHtml('guideResult', chip(`已导入 ${data.imported || 0} 条`, 'ok'));
      } catch (err) {
        setText('guideResult', String(err.message || err), true);
      }
    }
    function openKnowledgeManager() {
      window.location.href = `/knowledge/manage?${authQuery()}`;
    }
    async function loadRuntime() {
      try {
        const data = await api('/api/v1/admin/runtime/status');
        const reachable = Object.values(data.runtime.ports || {}).filter((port) => port.reachable).length;
        setHtml('runtimeSummary', chip(`可达端口：${reachable}`, 'ok') + chip(`健康：${data.health.status}`,'ok'));
        const platformRows = Object.entries(data.runtime.platforms || {}).map(([name, platform]) => `<tr><td>${safe(name)}</td><td>${platform.configured ? chip('已配置','ok') : chip('缺凭据','warn')}</td><td>${safe((platform.present_env || []).join(', ') || '-')}</td><td>${safe((platform.missing_env || []).join(', ') || '-')}</td></tr>`);
        setHtml('runtimeResult', table(['平台','状态','已加载','缺少'], platformRows));
      } catch (err) {
        setText('runtimeResult', String(err.message || err), true);
      }
    }
    function renderWecomMcpStatus(data) {
      const rows = ['doc','todo'].map((kind) => {
        const item = data[kind] || {};
        const tools = (item.tools || []).join(', ') || '-';
        const state = item.configured ? chip(item.reachable === false ? '已配置但不可达' : '已配置', item.reachable === false ? 'bad' : 'ok') : chip('未配置','warn');
        return `<tr><td>${safe(item.label || kind)}</td><td>${state}</td><td>${safe(item.url_masked || '-')}</td><td>${safe(tools)}</td><td>${safe(item.error || '')}</td></tr>`;
      });
      setHtml('wecomMcpStatus', table(['能力','状态','URL（已脱敏）','已发现工具','错误'], rows));
    }
    async function loadWecomMcpStatus(discover=false) {
      try {
        const data = await api(`/api/v1/admin/wecom/mcp/status?discover=${discover ? 'true' : 'false'}`);
        renderWecomMcpStatus(data);
      } catch (err) {
        setText('wecomMcpStatus', String(err.message || err), true);
      }
    }
    function phase1StatusChip(status) {
      if (status === 'ready') return chip('可用', 'ok');
      if (status === 'degraded') return chip('降级可用', 'warn');
      if (status === 'blocked') return chip('阻塞', 'bad');
      return chip('需配置', 'warn');
    }
    async function loadPhase1Readiness() {
      try {
        const data = await api('/api/v1/admin/phase1/readiness');
        const items = Object.values(data.items || {});
        const rows = items.map((item) => `<tr><td>${safe(item.name)}</td><td>${phase1StatusChip(item.status)}</td><td>${safe(item.summary || '')}</td><td>${safe(item.next_action || '')}</td></tr>`);
        const gate = data.phase2_gate || {};
        const head = `${phase1StatusChip(data.overall_status)} ${safe(gate.recommendation || '')}`;
        setHtml('phase1Readiness', `<p>${head}</p>` + table(['能力','状态','当前结论','下一步'], rows));
      } catch (err) {
        setText('phase1Readiness', String(err.message || err), true);
      }
    }
    async function saveWecomMcpConfig() {
      try {
        const payload = {
          doc_mcp_url: val('wecomDocMcpUrl'),
          todo_mcp_url: val('wecomTodoMcpUrl')
        };
        if (!payload.doc_mcp_url && !payload.todo_mcp_url) throw new Error('请至少填写一个 MCP StreamableHttp URL');
        const data = await api('/api/v1/admin/wecom/mcp/config', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
        renderWecomMcpStatus(data.status || {});
        const restart = data.restart_required ? '。当前进程未加载新变量，请重启 dashboard/gateway/wecom-bot 后生效' : '';
        setHtml('wecomMcpStatus', (el('wecomMcpStatus').innerHTML || '') + `<p>${chip('已保存','ok')} ${safe((data.saved_keys || []).join(', '))}${safe(restart)}</p>`);
      } catch (err) {
        setText('wecomMcpStatus', String(err.message || err), true);
      }
    }
    window.integrationRows = [];
    function integrationStatusChip(status) {
      if (status === 'ready') return chip('正常', 'ok');
      if (status === 'degraded') return chip('需关注', 'warn');
      if (status === 'needs_config') return chip('需配置', 'warn');
      if (status === 'blocked') return chip('阻塞', 'bad');
      if (status === 'error') return chip('错误', 'bad');
      return chip(status || '未知', 'warn');
    }
    function integrationCategoryOptions(rows) {
      const select = el('integrationCategoryFilter');
      if (!select) return;
      const current = select.value;
      const categories = Array.from(new Set((rows || []).map(item => item.category).filter(Boolean))).sort();
      select.innerHTML = '<option value="">全部类别</option>' + categories.map(item => `<option value="${safe(item)}">${safe(item)}</option>`).join('');
      if (categories.includes(current)) select.value = current;
    }
    function configureIntegration(tab) {
      const btn = document.querySelector(`nav button[data-tab="${tab}"]`);
      if (btn) showTab(tab, btn);
    }
    function renderIntegrationCenter() {
      const category = val('integrationCategoryFilter');
      const status = val('integrationStatusFilter');
      const rows = (window.integrationRows || []).filter(item =>
        (!category || item.category === category) && (!status || item.status === status)
      );
      const tableRows = rows.map((item) => {
        const testButton = item.testable
          ? `<button class="secondary" onclick="testIntegration(${jsAttr(item.id)}, ${jsAttr(item.name)})">测试</button>`
          : '<button class="secondary" disabled>不可测</button>';
        const configButton = item.configure_tab
          ? `<button class="tonal" onclick="configureIntegration(${jsAttr(item.configure_tab)})">配置</button>`
          : '<button class="secondary" disabled>无配置页</button>';
        return `<tr><td>${safe(item.category)}</td><td><strong>${safe(item.name)}</strong><br><span class="chip">${safe(item.id)}</span></td><td>${integrationStatusChip(item.status)}</td><td>${safe(item.summary || '')}</td><td>${testButton} ${configButton}</td></tr>`;
      });
      setHtml('integrationList', table(['类别','工具/集成','状态','当前结论','操作'], tableRows));
    }
    async function loadIntegrations() {
      try {
        const data = await api('/api/v1/admin/integrations');
        window.integrationRows = data.items || [];
        const summary = data.summary || {};
        setHtml('integrationSummary',
          chip(`总数 ${summary.total || 0}`) +
          chip(`正常 ${summary.ready || 0}`, 'ok') +
          chip(`需关注 ${summary.degraded || 0}`, summary.degraded ? 'warn' : '') +
          chip(`需配置 ${summary.needs_config || 0}`, summary.needs_config ? 'warn' : '') +
          chip(`阻塞/错误 ${(summary.blocked || 0) + (summary.error || 0)}`, (summary.blocked || summary.error) ? 'bad' : '')
        );
        integrationCategoryOptions(window.integrationRows);
        renderIntegrationCenter();
      } catch (err) {
        setText('integrationSummary', String(err.message || err), true);
      }
    }
    async function testIntegration(integrationId, name) {
      try {
        const query = prompt(`请输入 ${name || integrationId} 的测试问题或关键词`, '企业 AI 助手') || '';
        const data = await api('/api/v1/admin/integrations/test', {
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({integration_id: integrationId, query})
        });
        const status = data.ok ? chip(`测试通过，耗时 ${data.elapsed_ms}ms`, 'ok') : chip(`测试未通过，耗时 ${data.elapsed_ms}ms`, 'bad');
        setHtml('integrationTestResult', `${status}<pre>${safe(data.result || '')}</pre>`);
        await loadIntegrations();
      } catch (err) {
        setText('integrationTestResult', String(err.message || err), true);
      }
    }
    function testSelectedIntegration() {
      const rows = window.integrationRows || [];
      if (!rows.length) {
        setText('integrationTestResult', '请先刷新全部状态。', true);
        return;
      }
      const first = rows.find(item => item.testable && item.status !== 'ready') || rows.find(item => item.testable);
      if (!first) {
        setText('integrationTestResult', '当前没有可测试项目。', true);
        return;
      }
      testIntegration(first.id, first.name);
    }
    (async function init() {
      try {
        const profile = await loadProfile();
        if (profile && profile.role === 'hr_specialist') {
          await loadAdminUsers(false);
          await loadLeaveRealtimeStatus();
          return;
        }
        await loadBots();
        await loadAdminUsers(false);
        await loadEmployeeBots();
        await loadModels();
        await loadMailAccounts();
        await loadPublicDataSources();
        await loadIntegrations();
        await loadRuntime();
        await loadRateminStatus();
        await loadRateminDirectory();
        await loadWecomMcpStatus(false);
        await loadPhase1Readiness();
        await loadOverviewStats();
      } catch (err) {
        const msg = String(err.message || err);
        el('identity').textContent = '验证失败';
        const btn = document.createElement('button');
        btn.className = 'primary';
        btn.textContent = '刷新链接';
        btn.onclick = async () => {
          try {
            const resp = await fetch('/api/v1/admin/refresh-token', {
              method: 'POST',
              headers: authHeaders()
            });
            if (!resp.ok) throw new Error((await resp.json()).detail || '刷新失败');
            const data = await resp.json();
            sessionStorage.setItem('admin_token', data.admin_token);
            window.location.reload();
          } catch (e) {
            setText('profileBox', '刷新失败: ' + (e.message || e), true);
          }
        };
        const box = document.getElementById('profileBox');
        box.innerHTML = '';
        box.appendChild(document.createTextNode(msg));
        box.appendChild(document.createElement('br'));
        box.appendChild(btn);
      }
    })();
    async function loadOverviewStats() {
      try {
        const now = new Date();
        setHtml('statsTime', `<span class="chip">统计时间：${now.toLocaleString('zh-CN')}</span> <button class="secondary" onclick="loadOverviewStats()">刷新</button>`);
        await loadPhase1Readiness();
        // User stats
        if (window.allUsers && window.allUsers.length) {
          const total = window.allUsers.length;
          const active = window.allUsers.filter(u => u.bot_status === 'active').length;
          const paused = window.allUsers.filter(u => u.bot_status === 'paused').length;
          const disabled = window.allUsers.filter(u => u.bot_status === 'disabled').length;
          setHtml('userStats', `总计 ${total} 人 | ${chip('已开通','ok')} ${active} | ${chip('已暂停','warn')} ${paused} | ${chip('已关闭','bad')} ${disabled}`);
          setHtml('botStats', `开通率 ${total ? Math.round(active/total*100) : 0}% (${active}/${total})`);
        }
        // Knowledge stats
        try {
          const kb = await api('/api/v1/admin/knowledge/permissions?space_id=');
          setHtml('knowledgeStats', `可见范围 ${(kb.visible_scopes||[]).length} 个 | ${chip('管理员:'+(kb.can_manage_organization?'是':'否'))}`);
        } catch(err) { setHtml('knowledgeStats', '暂无知识库数据'); }
      } catch (err) {
        setText('statsTime', String(err.message || err), true);
      }
    }
  </script>
</body>
</html>
        """
    html = html.replace(
        '<div id="identity" class="chip">未验证</div>',
        f'<div id="identity" class="chip">{initial_identity}</div>',
    )
    html = html.replace(
        '<div class="panel"><h3>管理员身份</h3><div id="profileBox" class="status">等待验证</div></div>',
        f'<div class="panel"><h3>管理员身份</h3><div id="profileBox" class="status">{initial_profile_box}</div></div>',
    )
    return HTMLResponse(html)


@app.get("/platform/bots/manage", response_class=HTMLResponse)
def platform_bot_management_page():
    return HTMLResponse(
        """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Platform Bot Manager</title>
  <style>
    body { font-family:"Segoe UI Variable","Segoe UI",system-ui,-apple-system,sans-serif; margin:0 auto; max-width:1080px; padding:24px 32px; color:#1a1a1a; background:#faf9f8; font-size:14px; line-height:1.5; }
    h1 { font-size:24px; font-weight:600; letter-spacing:-.02em; }
    h2 { font-size:18px; font-weight:600; margin-bottom:12px; }
    p { color:#616161; margin-bottom:12px; font-size:13px; }
    textarea, input, select { width:100%; border:1px solid #e0e0e0; border-radius:4px; padding:8px 10px; margin-top:6px; font:inherit; font-size:13px; outline:none; transition:border-color .15s; }
    textarea:focus, input:focus, select:focus { border-color:#0078d4; box-shadow:0 0 0 3px rgba(0,120,212,.15); }
    textarea { min-height:120px; resize:vertical; }
    .grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; }
    .card { background:#fff; border:1px solid #e0e0e0; border-radius:8px; padding:18px; margin-bottom:16px; box-shadow:0 2px 4px rgba(0,0,0,.04); }
    button { border:1px solid transparent; border-radius:4px; padding:7px 16px; background:#0078d4; color:#fff; font:inherit; font-size:13px; font-weight:500; cursor:pointer; margin-top:8px; transition:background .15s; }
    button:hover { background:#106ebe; }
    pre { background:#f3f3f3; padding:12px; border-radius:4px; white-space:pre-wrap; font-size:12px; }
    #status { min-height:20px; color:#616161; font-size:12px; margin-bottom:12px; }
  </style>
</head>
<body>
  <h1>平台机器人管理</h1>
  <p>这里是管理员或负责人使用的平台统一开通入口。普通员工不需要自行创建机器人、不需要配置回调地址、不需要填写 Token 或 AESKey。保存后如提示需要重启，请重启对应服务再进行消息测试。</p>
  <div id="status"></div>
  <div class="grid">
    <div class="card">
      <h2>企业微信 BOT</h2>
      <input id="wecomDisplayName" placeholder="显示名称，默认 企业 AI 助手">
      <p>必填：bot_id、bot_secret。需要调用通讯录、文档、消息等应用能力时，同时填写 corp_id、agent_id、secret。</p>
      <textarea id="wecomCredentials" rows="8" placeholder='JSON 格式，例如 { "bot_id": "...", "bot_secret": "...", "corp_id": "...", "agent_id": "...", "secret": "...", "callback_token": "...", "callback_aes_key": "..." }'></textarea>
      <button onclick="activate('wecom', 'wecomCredentials', 'wecomDisplayName')">保存并接管</button>
    </div>
    <div class="card">
      <h2>飞书 BOT</h2>
      <input id="feishuDisplayName" placeholder="显示名称，默认 飞书 AI 助手">
      <p>必填：app_id、app_secret。国内飞书 domain 可填 feishu/cn，国际版可填 lark/intl。</p>
      <textarea id="feishuCredentials" rows="8" placeholder='JSON 格式，例如 { "app_id": "...", "app_secret": "...", "domain": "feishu" }'></textarea>
      <button onclick="activate('feishu', 'feishuCredentials', 'feishuDisplayName')">保存并接管</button>
    </div>
    <div class="card">
      <h2>钉钉 BOT</h2>
      <input id="dingtalkDisplayName" placeholder="显示名称，默认 钉钉 AI 助手">
      <p>必填：client_id、client_secret、robot_code。平台会同时写入兼容旧配置的 app_key/app_secret 别名。</p>
      <textarea id="dingtalkCredentials" rows="8" placeholder='JSON 格式，例如 { "client_id": "...", "client_secret": "...", "robot_code": "..." }'></textarea>
      <button onclick="activate('dingtalk', 'dingtalkCredentials', 'dingtalkDisplayName')">保存并接管</button>
    </div>
  </div>
  <pre id="result"></pre>
  <script>
    async function refresh() {
      const data = await fetch('/api/v1/platform/bots').then(r => r.json());
      document.getElementById('status').innerHTML = data.platforms.map(p =>
        `<div class="card"><strong>${p.platform_label || p.platform}</strong> | 启用: ${p.enabled} | 平台接管: ${p.managed_by_platform} | 显示名: ${p.display_name} | 可见范围: ${p.visibility_scope || '-'}<br>已配置: ${(p.configured_keys || []).join(', ') || '-'}<br>缺少配置: ${(p.missing_keys || []).join(', ') || '-'}<br>当前进程缺少环境变量: ${(p.missing_process_env || []).join(', ') || '-'}<br>是否需要重启: ${p.restart_required ? '是' : '否'}<br>下一步: ${p.next_action || '-'}</div>`
      ).join('');
    }
    async function activate(platform, credId, displayId) {
      const credentials = JSON.parse(document.getElementById(credId).value || '{}');
      const displayName = document.getElementById(displayId).value || '';
      const payload = {
        credentials,
        activated_by: 'platform-admin',
        display_name: displayName,
        visibility_scope: 'all',
        auto_permissions: ['docs.full', 'knowledge.readwrite', 'contacts.read']
      };
      const resp = await fetch(`/api/v1/platform/bots/${platform}/activate`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      });
      const data = await resp.json();
      document.getElementById('result').textContent = JSON.stringify(data, null, 2);
      await refresh();
    }
    refresh();
  </script>
</body>
</html>
        """
    )


@app.get("/api/v1/knowledge/{entry_id}/open", response_class=HTMLResponse)
def open_knowledge_entry(entry_id: str, user_id: str = "", space_id: str = ""):
    from html import escape
    from src.knowledge.acl import may_read, resolve_role

    kr = get_knowledge_repo()
    entry = kr.get(entry_id)
    if entry is None:
        raise HTTPException(404, f"Entry {entry_id} not found")
    if user_id:
        role = resolve_role(user_id, space_id)
        if not may_read(role, entry.owner_type.value, entry.owner_id, user_id):
            raise HTTPException(403, "Permission denied")

    title = str(entry.metadata.get("title", "")).strip() or entry.id
    source_url = _knowledge_source_open_url(entry)
    source_link = f'<p><a href="{escape(source_url)}" target="_blank">打开原始来源</a></p>' if source_url else ""
    body = escape(entry.content)
    return HTMLResponse(
        f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 2rem auto; max-width: 960px; line-height: 1.65; color: #222; padding: 0 1rem; }}
    pre {{ white-space: pre-wrap; word-break: break-word; background: #f6f8fa; padding: 1rem; border-radius: 8px; }}
    .meta {{ color: #666; margin-bottom: 1rem; }}
  </style>
</head>
<body>
  <h1>{escape(title)}</h1>
  <div class="meta">范围：{escape(owner_type_label(entry.owner_type.value))} / {escape(entry.owner_id)}</div>
  {source_link}
  <pre>{body}</pre>
</body>
</html>"""
    )


@app.get("/api/v1/knowledge/{entry_id}/source")
def download_knowledge_source(entry_id: str, user_id: str = "", space_id: str = ""):
    from src.knowledge.acl import may_read, resolve_role

    kr = get_knowledge_repo()
    entry = kr.get(entry_id)
    if entry is None:
        raise HTTPException(404, f"Entry {entry_id} not found")
    if user_id:
        role = resolve_role(user_id, space_id)
        if not may_read(role, entry.owner_type.value, entry.owner_id, user_id):
            raise HTTPException(403, "Permission denied")

    source_path = str(entry.metadata.get("source_path", "")).strip()
    if not source_path:
        raise HTTPException(404, "No source file available")
    resolved = Path(source_path)
    if not resolved.is_absolute():
        repo_root = Path(__file__).resolve().parents[2]
        resolved = (repo_root / source_path).resolve()
    allowed_roots = [
        Path(__file__).resolve().parents[2].resolve(),
        Path("./data/files").resolve(),
    ]
    if not any(str(resolved).startswith(str(root)) for root in allowed_roots):
        raise HTTPException(403, "Source path is outside allowed roots")
    if not resolved.is_file():
        raise HTTPException(404, "Source file not found")
    return FileResponse(str(resolved), filename=resolved.name)


# ---- Document Download ----

@app.get("/api/v1/documents/{filename:path}")
def download_document(filename: str):
    """Download a generated document file."""
    docs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "documents")
    try:
        filepath = resolve_document_download_path(docs_dir, filename)
    except FileNotFoundError:
        raise HTTPException(404, "File not found")
    return FileResponse(filepath, filename=filename)


def _list_accessible_by_platform(kr: Any, *, user_id: str, query: str = "", space_id: str = "", limit: int = 50, platform: str = "wecom") -> list[KnowledgeEntry]:
    from src.knowledge.acl import resolve_role, visible_scopes
    from src.knowledge.contracts import KnowledgeOwnerType

    role = resolve_role(user_id, space_id, platform=platform)
    lowered_query = query.strip().lower()
    results: list[KnowledgeEntry] = []
    seen: set[str] = set()
    for owner_type, owner_id in visible_scopes(role, user_id, platform=platform):
        try:
            entries = kr.list_for_owner(KnowledgeOwnerType(owner_type), owner_id)
        except Exception:
            entries = []
        for entry in entries:
            if entry.id in seen:
                continue
            haystack = f"{entry.metadata.get('title', '')}\n{' '.join(entry.tags)}\n{entry.content}".lower()
            if lowered_query and lowered_query not in haystack:
                continue
            seen.add(entry.id)
            results.append(entry)
            if len(results) >= limit:
                return results
    return results


def _knowledge_entry_to_dict(entry: KnowledgeEntry, *, user_id: str = "", space_id: str = "", platform: str = "wecom") -> dict[str, Any]:
    can_read = True
    can_write = False
    if user_id:
        from src.knowledge.acl import may_read, may_write, resolve_role

        role = resolve_role(user_id, space_id, platform=platform)
        can_read = may_read(role, entry.owner_type.value, entry.owner_id, user_id, platform=platform)
        can_write = may_write(role, entry.owner_type.value, entry.owner_id, user_id, platform=platform)
    return {
        "id": entry.id,
        "owner_type": entry.owner_type.value,
        "owner_type_label": owner_type_label(entry.owner_type.value),
        "owner_id": entry.owner_id,
        "title": str(entry.metadata.get("title", "")),
        "content": entry.content,
        "tags": entry.tags,
        "metadata": entry.metadata,
        "can_read": can_read,
        "can_write": can_write,
        "open_url": build_knowledge_open_url(entry.id),
        "source_url": _knowledge_source_open_url(entry),
    }


def _knowledge_source_open_url(entry: KnowledgeEntry) -> str:
    source_type = str(entry.metadata.get("source_type", "")).strip()
    if source_type in {"file", "builtin_company_guide"}:
        return build_knowledge_open_url(entry.id).replace("/open", "/source")
    source_url = str(entry.metadata.get("source_url", "")).strip()
    if source_url:
        return source_url
    return ""
