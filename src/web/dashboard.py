from __future__ import annotations

import csv
import io
import json
import logging
import os
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
from src.web.admin_auth import require_admin_context_from_request, require_user_context_from_request
from src.web.middleware import add_request_id, check_rate_limit, require_auth

logger = logging.getLogger(__name__)

app = FastAPI(title="Ant Colony API", version="0.3.0")

_PUBLIC_PATHS = {"/", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json", "/admin/console", "/knowledge/manage", "/knowledge/user"}
_PUBLIC_PREFIXES = ("/api/v1/user/knowledge/",)
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

class EmployeeBotActivationRequest(BaseModel):
    platform: str = "wecom"
    user_id: str
    display_name: str = ""
    scope: str = "personal"
    permissions: list[str] = []
    notify: bool = True

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


@app.get("/api/v1/admin/profile")
def admin_profile(request: Request):
    context = require_admin_context_from_request(request)
    from src.knowledge.acl import resolve_role, visible_scopes
    from src.platform.org_graph import OrgGraphService

    role = resolve_role(context["user_id"], platform=context["platform"])
    graph = OrgGraphService()
    profile = graph.get_user_profile(context["platform"], context["user_id"]) or {}
    return {
        **context,
        "role": role.name,
        "name": profile.get("name", ""),
        "departments": profile.get("departments", []),
        "leader_departments": profile.get("leader_departments", []),
        "visible_scopes": [
            {"owner_type": owner_type, "owner_id": owner_id}
            for owner_type, owner_id in visible_scopes(role, context["user_id"], platform=context["platform"])
        ],
        "can_activate_bots": True,
        "can_import_company_guides": role.value >= 4,
        "can_manage_knowledge": True,
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


@app.get("/api/v1/admin/employee-bots")
def admin_list_employee_bots(request: Request, platform: str = "", limit: int = 200):
    require_admin_context_from_request(request)
    from src.platform.employee_bot_service import list_employee_bot_assignments

    return {"assignments": list_employee_bot_assignments(platform=platform, limit=limit)}


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
    return delete_knowledge(entry_id, user_id=context["user_id"])


@app.post("/api/v1/admin/knowledge/promote")
def admin_promote_knowledge(req: KnowledgePromoteRequest, request: Request):
    context = require_admin_context_from_request(request)
    req.user_id = context["user_id"]
    req.platform = context["platform"]
    return promote_knowledge(req)


@app.get("/api/v1/user/knowledge/permissions")
def user_knowledge_permissions(request: Request, space_id: str = ""):
    context = require_user_context_from_request(request)
    return knowledge_permissions(user_id=context["user_id"], space_id=space_id, platform=context["platform"])


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
    return delete_knowledge(entry_id, user_id=context["user_id"])


@app.post("/api/v1/user/knowledge/promote")
def user_promote_knowledge(req: KnowledgePromoteRequest, request: Request):
    context = require_user_context_from_request(request)
    req.user_id = context["user_id"]
    req.platform = context["platform"]
    return promote_knowledge(req)


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
def delete_knowledge(entry_id: str, user_id: str = ""):
    kr = get_knowledge_repo()
    if not kr.delete(entry_id, user_id=user_id):
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
    syncer = OrgSynchronizer(space_registry=get_space_registry(), memory_dir="./data/memory")
    result = syncer.sync_all()
    return result

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
    except Exception as e:
        logger.warning("File index failed: %s", e)
        indexed = None
    return {
        "path": rel_path,
        "filename": file.filename,
        "size": len(content),
        "indexed": indexed,
        "knowledge_owner_type": owner_type,
        "knowledge_owner_id": owner_id,
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
    from src.orchestrator.cron_job import get_registry, run_no_agent
    reg = get_registry()
    job = reg.get(job_id)
    if not job:
        raise HTTPException(404, f"Job not found: {job_id}")
    result = run_no_agent(job.command) if job.no_agent else "(agent mode)"
    reg.record_run(job.id, "OK" if "FAILED" not in result else result[:100])
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
      --md-primary:#0b57d0; --md-on-primary:#fff; --md-primary-container:#d3e3fd;
      --md-secondary:#00639b; --md-surface:#f8fafd; --md-surface-container:#eef3f8;
      --md-surface-high:#e7edf5; --md-outline:#c4c7c5; --md-text:#1f1f1f;
      --md-muted:#5f6368; --md-error:#b3261e; --md-success:#0b8043;
      --radius:24px; --radius-small:14px;
    }
    * { box-sizing:border-box; }
    body { margin:0; background:var(--md-surface); color:var(--md-text); font-family:"Google Sans","Roboto","Noto Sans SC",Arial,sans-serif; }
    header { padding:28px 32px 16px; display:flex; gap:20px; justify-content:space-between; align-items:flex-end; }
    h1 { margin:0; font-size:34px; line-height:1.15; font-weight:600; }
    h2 { margin:0 0 14px; font-size:22px; font-weight:600; }
    h3 { margin:0 0 10px; font-size:16px; font-weight:600; }
    p { color:var(--md-muted); margin:0 0 14px; }
    main { padding:0 32px 32px; display:grid; grid-template-columns:360px 1fr; gap:20px; }
    .card { background:#fff; border:1px solid #e1e3e1; border-radius:var(--radius); padding:20px; box-shadow:0 1px 2px rgba(60,64,67,.08); }
    .stack { display:grid; gap:16px; }
    .grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; }
    label { display:block; color:var(--md-muted); font-size:13px; margin:10px 0 6px; }
    input, textarea, select { width:100%; border:1px solid var(--md-outline); border-radius:12px; padding:12px 14px; background:#fff; font:inherit; }
    textarea { min-height:180px; resize:vertical; }
    button { border:0; border-radius:999px; padding:11px 18px; background:var(--md-primary); color:var(--md-on-primary); font:inherit; cursor:pointer; }
    button.secondary { background:var(--md-primary-container); color:#0842a0; }
    button.tonal { background:var(--md-surface-high); color:var(--md-text); }
    button.danger { background:var(--md-error); color:white; }
    button:disabled { opacity:.45; cursor:not-allowed; }
    .actions { display:flex; gap:10px; flex-wrap:wrap; margin-top:14px; }
    .chip { display:inline-flex; align-items:center; border-radius:999px; padding:6px 10px; background:var(--md-surface-container); color:var(--md-muted); margin:0 6px 6px 0; font-size:13px; }
    .chip.ok { color:var(--md-success); background:#e6f4ea; }
    .chip.bad { color:var(--md-error); background:#fce8e6; }
    .list { display:grid; gap:10px; max-height:580px; overflow:auto; }
    .scope-tree { display:grid; gap:8px; }
    .scope-node { border:1px solid #e1e3e1; border-radius:16px; padding:12px; background:#fff; }
    .scope-node strong { display:block; margin-bottom:4px; }
    .scope-node.readonly { background:#fafafa; }
    .item { border:1px solid #e1e3e1; border-radius:18px; padding:14px; background:#fff; cursor:pointer; }
    .item.active { border-color:var(--md-primary); background:#f4f8ff; }
    .meta { color:var(--md-muted); font-size:13px; margin-top:6px; }
    table { width:100%; border-collapse:collapse; font-size:14px; }
    th, td { padding:10px; border-bottom:1px solid #e1e3e1; text-align:left; vertical-align:top; }
    .status { min-height:22px; color:var(--md-muted); }
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
        <p>系统会根据当前用户在企业微信中的角色、部门和负责人权限自动决定入库范围。</p>
        <div id="autoOwner" class="status">等待权限识别</div>
        <label>标签</label><input id="newTags" placeholder="逗号分隔">
        <label>正文</label><textarea id="newContent" placeholder="粘贴要入库的内容"></textarea>
        <button onclick="createEntry()">新增到知识库</button>
      </div>
      <div class="card">
        <h2>上传文档入库</h2>
        <p>上传后系统会立即解析并索引文档内容，默认归入当前用户有权限写入的知识库。</p>
        <input id="knowledgeFile" type="file" accept=".txt,.md,.docx,.pdf,.xlsx,.pptx,.csv,.json">
        <button onclick="uploadKnowledgeFile()">上传并索引</button>
        <div id="uploadStatus" class="status"></div>
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
          <div id="editStatus" class="status"></div>
        </div>
      </div>
    </section>
  </main>
  <script>
    const params = new URLSearchParams(location.search);
    const hasAdminToken = !!params.get('admin_token');
    const hasUserToken = !!params.get('user_token');
    const adminQuery = () => `platform=${encodeURIComponent(params.get('platform') || 'wecom')}&user_id=${encodeURIComponent(params.get('user_id') || '')}&admin_token=${encodeURIComponent(params.get('admin_token') || '')}`;
    const userQuery = () => `platform=${encodeURIComponent(params.get('platform') || 'wecom')}&user_id=${encodeURIComponent(params.get('user_id') || userId())}&user_token=${encodeURIComponent(params.get('user_token') || '')}`;
    function userId() { return document.getElementById('userId').value.trim() || params.get('user_id') || ''; }
    function setStatus(id, text, bad=false) { const el = document.getElementById(id); el.textContent = text; el.style.color = bad ? 'var(--md-error)' : 'var(--md-muted)'; }
    function scopeLabel(scope) {
      const labels = {organization:'公司', department:'部门', project:'项目', personal:'个人'};
      return `${labels[scope.owner_type] || scope.owner_type} / ${scope.owner_id}`;
    }
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
        return `<div class="scope-node ${canWrite ? '' : 'readonly'}"><strong>${scopeLabel(scope)}</strong><span class="chip ${canWrite ? 'ok' : ''}">${canWrite ? '可维护' : '只读'}</span><span class="chip">条目 ${counts[key] || 0}</span></div>`;
      }).join('');
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
          `<div class="meta">可写范围：${(perm.writable_scopes || []).map(scopeLabel).join('；') || '仅可查看'}</div>`;
        document.getElementById('autoOwner').innerHTML = `<span class="chip ok">默认入库：${scopeLabel(window.defaultWriteScope)}</span>`;
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
      const root = document.getElementById('result');
      root.innerHTML = '';
      const entries = data.entries || data.results || [];
      window.currentEntries = entries;
      renderScopeGroups(window.currentPermissions || {}, entries);
      for (const item of entries) {
        const row = document.createElement('div');
        row.className = 'item';
        row.innerHTML = `<strong>${item.title || item.id}</strong><div class="meta">${item.owner_type_label || item.owner_type} / ${item.owner_id} / ${item.can_write ? '可编辑' : '只读'}</div>`;
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
        };
        root.appendChild(row);
      }
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
        const payload = {
          text: document.getElementById('newContent').value,
          title: document.getElementById('newTitle').value,
          owner_type: 'auto',
          owner_id: '',
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
    async function uploadKnowledgeFile() {
      try {
        await loadPermissions();
        const fileInput = document.getElementById('knowledgeFile');
        if (!fileInput.files || !fileInput.files.length) throw new Error('请先选择要上传的文档文件');
        const form = new FormData();
        form.append('file', fileInput.files[0]);
        form.append('user_id', userId());
        form.append('space_id', document.getElementById('spaceId').value.trim());
        form.append('knowledge_owner_type', 'auto');
        form.append('knowledge_owner_id', '');
        const url = knowledgeUrl('/api/v1/admin/knowledge/files/upload', '/api/v1/user/knowledge/files/upload', '/api/v1/files');
        const data = await requestJson(url, {method:'POST', body:form});
        setStatus('uploadStatus', data.indexed ? `上传并索引成功：${data.filename}` : `文件已上传，但未提取到可索引内容：${data.filename}`, !data.indexed);
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
      const url = knowledgeUrl(`/api/v1/admin/knowledge/${encodeURIComponent(entryId)}`, `/api/v1/user/knowledge/${encodeURIComponent(entryId)}`, `/api/v1/knowledge/${encodeURIComponent(entryId)}?user_id=${encodeURIComponent(userId())}`);
      await requestJson(url, {method: 'DELETE'});
      setStatus('editStatus', '删除成功');
      await loadEntries();
      } catch (err) { setStatus('editStatus', String(err.message || err), true); }
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
def admin_console_page():
    return HTMLResponse(
        """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>管理员控制台</title>
  <style>
    :root {
      --md-primary:#0b57d0; --md-on-primary:#fff; --md-primary-container:#d3e3fd;
      --md-secondary:#00639b; --md-surface:#f8fafd; --md-surface-container:#eef3f8;
      --md-surface-high:#e7edf5; --md-outline:#c4c7c5; --md-text:#1f1f1f;
      --md-muted:#5f6368; --md-error:#b3261e; --md-success:#0b8043; --md-warn:#b06000;
      --radius:24px; --radius-small:14px;
    }
    * { box-sizing: border-box; }
    body { margin:0; background:var(--md-surface); color:var(--md-text); font-family:"Google Sans","Roboto","Noto Sans SC",Arial,sans-serif; line-height:1.45; }
    header { padding:28px 32px 16px; display:flex; justify-content:space-between; gap:20px; align-items:flex-end; }
    h1 { margin:0; font-size:36px; line-height:1.1; font-weight:600; }
    h2 { margin:0 0 14px; font-size:22px; font-weight:600; }
    h3 { margin:0 0 10px; font-size:16px; font-weight:600; }
    p { margin:0 0 14px; color:var(--md-muted); }
    main { display:grid; grid-template-columns:260px 1fr; gap:20px; padding:0 32px 32px; }
    nav { background:var(--md-surface-container); border-radius:var(--radius); padding:12px; height:max-content; position:sticky; top:16px; }
    nav button { width:100%; text-align:left; border:0; border-radius:999px; background:transparent; color:var(--md-text); padding:12px 16px; margin:2px 0; cursor:pointer; font:inherit; }
    nav button.active { background:var(--md-primary-container); color:#0842a0; }
    section { display:none; }
    section.active { display: block; }
    .grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:16px; }
    .two { grid-template-columns:repeat(2,minmax(0,1fr)); }
    .panel { background:#fff; border:1px solid #e1e3e1; border-radius:var(--radius); padding:20px; box-shadow:0 1px 2px rgba(60,64,67,.08); }
    .span { grid-column:1 / -1; }
    label { display:block; color:var(--md-muted); font-size:13px; margin:10px 0 6px; }
    input, textarea, select { width:100%; border:1px solid var(--md-outline); border-radius:12px; padding:12px 14px; background:#fff; font:inherit; }
    textarea { min-height:92px; resize:vertical; }
    .primary, button.primary { border:0; border-radius:999px; padding:11px 18px; background:var(--md-primary); color:#fff; font:inherit; cursor:pointer; }
    button.secondary { border:0; border-radius:999px; padding:11px 18px; background:var(--md-primary-container); color:#0842a0; font:inherit; cursor:pointer; }
    button.tonal { border:0; border-radius:999px; padding:11px 18px; background:var(--md-surface-high); color:var(--md-text); font:inherit; cursor:pointer; }
    button.danger { border:0; border-radius:999px; padding:11px 18px; background:var(--md-error); color:#fff; font:inherit; cursor:pointer; }
    table { width:100%; border-collapse:collapse; font-size:14px; }
    th,td { border-bottom:1px solid #e1e3e1; padding:10px; text-align:left; vertical-align:top; }
    .chip { display:inline-flex; border-radius:999px; padding:6px 10px; background:var(--md-surface-container); color:var(--md-muted); margin:0 6px 6px 0; font-size:13px; }
    .chip.ok { color:var(--md-success); background:#e6f4ea; }
    .chip.warn { color:var(--md-warn); background:#fef7e0; }
    .chip.bad { color:var(--md-error); background:#fce8e6; }
    .actions { display:flex; gap:10px; flex-wrap:wrap; margin-top:14px; }
    .status { min-height:22px; color:var(--md-muted); }
    pre { background:var(--md-surface-container); border-radius:var(--radius-small); padding:12px; white-space:pre-wrap; overflow:auto; }
    @media (max-width: 980px) { header, main, .grid, .two { display:block; } main { padding:0 16px 24px; } nav, .panel { margin-bottom:16px; } }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>管理员控制台</h1>
      <p>统一开通平台 Bot、给员工分配 AI 助手、管理公司知识库和验证运行状态。</p>
    </div>
    <div id="identity" class="chip">未验证</div>
  </header>
  <main>
    <nav>
      <button class="active" onclick="showTab('overview', this)">总览</button>
      <button onclick="showTab('bots', this)">平台 Bot 开通</button>
      <button onclick="showTab('employees', this)">员工 AI 助手</button>
      <button onclick="showTab('knowledge', this)">知识库管理</button>
      <button onclick="showTab('runtime', this)">运行验证</button>
      <button onclick="showTab('help', this)">操作说明</button>
    </nav>
    <div>
      <section id="overview" class="active">
        <div class="grid">
          <div class="panel"><h3>管理员身份</h3><div id="profileBox" class="status">等待验证</div></div>
          <div class="panel"><h3>平台状态</h3><div id="platformSummary" class="status">等待加载</div></div>
          <div class="panel"><h3>运行状态</h3><div id="runtimeSummary" class="status">等待加载</div></div>
        </div>
      </section>
      <section id="bots">
        <div class="grid">
          <div class="panel span">
            <h2>平台 Bot 统一开通</h2>
            <p>平台会自动检查服务器环境变量、配置文件和历史配置。管理员通常只需要审核状态并点击确认接管；只有系统提示仍缺少凭据时，才展开高级配置补录一次。</p>
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
            <h2>给员工开通 AI 助手</h2>
            <p>这里不是让员工自己创建独立机器人，而是把平台统一 Bot 分配给指定员工，并发送企微开通通知。</p>
            <p class="muted">知识范围和操作权限由平台根据员工在企业 IM 中的组织架构、部门归属、负责人/管理员身份自动计算，管理员只确认开通，不手工指定范围。</p>
            <label>平台</label><select id="employeePlatform"><option value="wecom">企业微信</option><option value="feishu">飞书</option><option value="dingtalk">钉钉</option></select>
            <label>员工用户 ID</label><input id="employeeUserId" placeholder="例如 MaGe 或同事企微 user_id">
            <label>显示名称</label><input id="employeeBotName" placeholder="企业 AI 助手">
            <div class="actions">
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
      <section id="help">
        <div class="panel">
          <h2>页面操作说明</h2>
          <table>
            <tbody>
              <tr><th>总览</th><td>确认当前企业 IM 用户是否通过管理员校验，快速查看平台与运行状态。</td></tr>
              <tr><th>平台 Bot 开通</th><td>系统会自动检查服务器环境变量、配置文件和历史配置。管理员先审核状态，再点击确认自动接管；只有系统明确提示仍缺少凭据时，才展开高级配置补录。</td></tr>
              <tr><th>员工 AI 助手</th><td>输入同事企业 IM 用户 ID，管理员确认后平台自动按企业 IM 组织架构分配知识范围和权限，并在企微下直接发送开通通知。</td></tr>
              <tr><th>知识库管理</th><td>说明书作为普通公司级知识文档统一纳入知识库；所有新增、更新、删除、升级操作都按当前企微组织权限自动适配。</td></tr>
              <tr><th>运行验证</th><td>检查端口和平台环境变量是否就绪。飞书、钉钉没有真实账号时只能看模拟或缺凭据状态。</td></tr>
              <tr><th>管理员身份</th><td>页面 URL 必须包含 platform、user_id、admin_token。后端会校验令牌签名和该用户是否是对应 IM 平台管理员。</td></tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  </main>
  <script>
    const params = new URLSearchParams(location.search);
    const authQuery = () => `platform=${encodeURIComponent(params.get('platform') || 'wecom')}&user_id=${encodeURIComponent(params.get('user_id') || '')}&admin_token=${encodeURIComponent(params.get('admin_token') || '')}`;
    const el = (id) => document.getElementById(id);
    const val = (id) => (el(id)?.value || '').trim();
    const safe = (value) => String(value ?? '').replace(/[&<>"']/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
    function showTab(id, btn) {
      document.querySelectorAll('section').forEach((section) => section.classList.remove('active'));
      document.querySelectorAll('nav button').forEach((button) => button.classList.remove('active'));
      el(id).classList.add('active');
      btn.classList.add('active');
    }
    async function api(path, options = {}) {
      const joiner = path.includes('?') ? '&' : '?';
      const resp = await fetch(`${path}${joiner}${authQuery()}`, options);
      const contentType = resp.headers.get('content-type') || '';
      const data = contentType.includes('application/json') ? await resp.json() : {detail: await resp.text()};
      if (!resp.ok) throw new Error(data.detail || data.error || JSON.stringify(data));
      return data;
    }
    function chip(text, cls='') { return `<span class="chip ${safe(cls)}">${safe(text)}</span>`; }
    function setHtml(id, html) { el(id).innerHTML = html; }
    function setText(id, text, bad=false) {
      const node = el(id);
      node.textContent = text;
      node.style.color = bad ? 'var(--md-error)' : 'var(--md-muted)';
    }
    function table(headers, rows) {
      const head = headers.map((item) => `<th>${safe(item)}</th>`).join('');
      const body = rows.length ? rows.join('') : `<tr><td colspan="${headers.length}">暂无数据</td></tr>`;
      return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
    }
    async function loadProfile() {
      const profile = await api('/api/v1/admin/profile');
      el('identity').textContent = `${profile.platform} / ${profile.user_id} / ${profile.role}`;
      setHtml('profileBox', [
        chip(`用户：${profile.user_id}`, 'ok'),
        chip(`角色：${profile.role}`, 'ok'),
        chip(`部门：${(profile.departments || []).join(', ') || '-'}`)
      ].join(''));
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
        const rows = (data.assignments || []).map((assignment) => `<tr><td>${safe(assignment.platform)}</td><td>${safe(assignment.user_id)}</td><td>${safe(assignment.display_name)}</td><td>${safe(assignment.scope)}</td><td>${assignment.status === 'active' ? chip('已开通','ok') : chip('已停用','bad')}</td><td>${safe(assignment.notify_status || '-')}</td></tr>`);
        setHtml('employeeList', table(['平台','员工','名称','自动范围','状态','通知'], rows));
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
        setHtml('employeeResult', chip('员工 AI 助手已开通','ok') + chip(`通知：${data.assignment?.notify_status || '-'}`));
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
        setHtml('employeeResult', chip(`状态：${data.assignment?.status || '已停用'}`, 'warn'));
        await loadEmployeeBots();
      } catch (err) {
        setText('employeeResult', String(err.message || err), true);
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
    (async function init() {
      try {
        await loadProfile();
        await loadBots();
        await loadEmployeeBots();
        await loadRuntime();
      } catch (err) {
        el('identity').textContent = '验证失败';
        setText('profileBox', String(err.message || err), true);
      }
    })();
  </script>
</body>
</html>
        """
    )


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
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 2rem auto; max-width: 1080px; padding: 0 1rem; color: #222; }
    textarea, input, select { width: 100%; padding: .75rem; margin-top: .5rem; }
    .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; }
    .card { border: 1px solid #ddd; border-radius: 10px; padding: 1rem; margin-bottom: 1rem; }
    button { padding: .75rem 1rem; margin-top: .75rem; cursor: pointer; }
    pre { background: #f6f8fa; padding: 1rem; border-radius: 8px; white-space: pre-wrap; }
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
