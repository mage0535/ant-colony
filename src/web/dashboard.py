from __future__ import annotations

import csv
import io
import json
import logging
import os
import time
from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from src.analysis.role_analyzer import GroupMessageAnalyzer, RoleAnalyzer
from src.isolation.file_store import IsolatedFileStore
from src.knowledge.contracts import KnowledgeEntry, KnowledgeOwnerType
from src.knowledge.collector import KnowledgeCollector
from src.knowledge.repository_factory import build_knowledge_repository
from src.models.contracts import Task, TaskStatus
from src.pool.agent_pool import AgentPool
from src.rooms.space_registry import SpaceRegistry
from src.store.database import Database
from src.store.task_repo import TaskRepository
from src.web.document_paths import resolve_document_download_path
from src.web.middleware import add_request_id, check_rate_limit, require_auth

logger = logging.getLogger(__name__)

app = FastAPI(title="Ant Colony API", version="0.3.0")

_PUBLIC_PATHS = {"/", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}
MAX_UPLOAD_BYTES = int(os.environ.get("ANT_COLONY_MAX_FILE_BYTES", str(50 * 1024 * 1024)))


@app.middleware("http")
async def auth_and_rate_limit(request: Request, call_next):
    try:
        if request.url.path not in _PUBLIC_PATHS:
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
    owner_type: str = "project"
    owner_id: str = "*"
    tags: list[str] = []


class KnowledgeUpdateRequest(BaseModel):
    content: str
    title: str = ""
    tags: list[str] = []
    user_id: str = ""


class KnowledgePromoteRequest(BaseModel):
    entry_id: str
    target_owner_type: str
    target_owner_id: str
    new_entry_id: str = ""
    user_id: str = ""
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
        _knowledge_entry_to_dict(e)
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
    return {"entries": [_knowledge_entry_to_dict(e) for e in results[:limit]]}


@app.get("/api/v1/knowledge/accessible")
def list_accessible_knowledge(user_id: str, query: str = "", space_id: str = "", limit: int = 50):
    kr = get_knowledge_repo()
    results = kr.search_accessible(query, user_id=user_id, space_id=space_id, limit=limit) if query else kr.list_accessible(user_id=user_id, limit=limit)
    return {"entries": [_knowledge_entry_to_dict(e) for e in results]}

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
    role = resolve_role(req.user_id, "")
    if req.user_id and not may_write(role, entry.owner_type.value, entry.owner_id, req.user_id):
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
    role = resolve_role(req.user_id, "")
    if req.user_id and not may_write(role, entry.owner_type.value, entry.owner_id, req.user_id):
        raise HTTPException(403, "Permission denied")
    try:
        target_owner_type = KnowledgeOwnerType(req.target_owner_type)
    except ValueError:
        raise HTTPException(400, f"Invalid target_owner_type: {req.target_owner_type}")
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
def import_company_guides_api():
    from src.knowledge.company_guides import import_company_guides

    entries = import_company_guides(get_knowledge_repo())
    return {"imported": len(entries), "entries": [_knowledge_entry_to_dict(e) for e in entries]}

@app.post("/api/v1/knowledge/collect")
def collect_knowledge(req: KnowledgeCollectRequest):
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
    knowledge_owner_type: str = Form("project"),
    knowledge_owner_id: str = Form(""),
):
    content = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File exceeds the {MAX_UPLOAD_BYTES}-byte upload limit")
    store = _get_file_store()
    rel_path = store.write(user_id, space_id, file.filename or "unnamed", content)
    owner_type, owner_id = _resolve_knowledge_owner(
        knowledge_owner_type=knowledge_owner_type,
        knowledge_owner_id=knowledge_owner_id,
        user_id=user_id,
        space_id=space_id,
    )
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
) -> tuple[str, str]:
    raw_type = knowledge_owner_type if isinstance(knowledge_owner_type, str) else ""
    raw_id = knowledge_owner_id if isinstance(knowledge_owner_id, str) else ""
    normalized_type = (raw_type or "project").strip().lower()
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
  <title>Knowledge Manager</title>
</head>
<body class="bg-light">
  <div class="container py-4">
    <h1 class="h3 mb-3">知识库管理</h1>
    <div class="row g-3 mb-3">
      <div class="col-md-3"><input id="userId" class="form-control" placeholder="用户ID"></div>
      <div class="col-md-5"><input id="query" class="form-control" placeholder="关键词"></div>
      <div class="col-md-2"><button class="btn btn-primary w-100" onclick="loadEntries()">搜索/查看</button></div>
      <div class="col-md-2"><button class="btn btn-outline-secondary w-100" onclick="importGuides()">导入公司说明书</button></div>
    </div>
    <div class="mb-3">
      <textarea id="editor" class="form-control" rows="8" placeholder="点击下方条目后在这里编辑内容"></textarea>
    </div>
    <div class="row g-3 mb-4">
      <div class="col-md-3"><input id="entryId" class="form-control" placeholder="条目ID"></div>
      <div class="col-md-3"><input id="title" class="form-control" placeholder="标题"></div>
      <div class="col-md-3"><input id="tags" class="form-control" placeholder="标签，逗号分隔"></div>
      <div class="col-md-3 d-grid gap-2">
        <button class="btn btn-success" onclick="updateEntry()">保存更新</button>
        <button class="btn btn-danger" onclick="deleteEntry()">删除条目</button>
      </div>
    </div>
    <div id="result" class="list-group"></div>
  </div>
  <script>
    async function loadEntries() {
      const userId = document.getElementById('userId').value.trim();
      const query = document.getElementById('query').value.trim();
      const url = query
        ? `/api/v1/knowledge/accessible?user_id=${encodeURIComponent(userId)}&query=${encodeURIComponent(query)}`
        : `/api/v1/knowledge?user_id=${encodeURIComponent(userId)}`;
      const data = await fetch(url, {headers: {'Accept': 'application/json'}}).then(r => r.json());
      const root = document.getElementById('result');
      root.innerHTML = '';
      for (const item of (data.entries || data.results || [])) {
        const btn = document.createElement('button');
        btn.className = 'list-group-item list-group-item-action';
        btn.textContent = `[${item.owner_type}] ${item.title || item.id}`;
        btn.onclick = () => {
          document.getElementById('entryId').value = item.id;
          document.getElementById('title').value = item.title || '';
          document.getElementById('tags').value = (item.tags || []).join(', ');
          document.getElementById('editor').value = item.content || '';
        };
        root.appendChild(btn);
      }
    }
    async function importGuides() {
      await fetch('/api/v1/knowledge/import/company-guides', {method: 'POST'});
      await loadEntries();
    }
    async function updateEntry() {
      const entryId = document.getElementById('entryId').value.trim();
      const payload = {
        title: document.getElementById('title').value.trim(),
        content: document.getElementById('editor').value,
        tags: document.getElementById('tags').value.split(',').map(v => v.trim()).filter(Boolean),
        user_id: document.getElementById('userId').value.trim()
      };
      await fetch(`/api/v1/knowledge/${encodeURIComponent(entryId)}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      });
      await loadEntries();
    }
    async function deleteEntry() {
      const entryId = document.getElementById('entryId').value.trim();
      const userId = document.getElementById('userId').value.trim();
      await fetch(`/api/v1/knowledge/${encodeURIComponent(entryId)}?user_id=${encodeURIComponent(userId)}`, {method: 'DELETE'});
      await loadEntries();
    }
  </script>
</body>
</html>
        """
    )


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


def _knowledge_entry_to_dict(entry: KnowledgeEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "owner_type": entry.owner_type.value,
        "owner_id": entry.owner_id,
        "title": str(entry.metadata.get("title", "")),
        "content": entry.content,
        "tags": entry.tags,
        "metadata": entry.metadata,
    }
