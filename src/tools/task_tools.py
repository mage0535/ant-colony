from __future__ import annotations

import json
from typing import Any

from src.models.contracts import TaskDraft


def create_draft_tool(args: dict[str, Any]) -> str:
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


def query_tasks_tool(args: dict[str, Any]) -> str:
    from src.store.database import Database
    from src.store.task_repo import TaskRepository

    repo = TaskRepository(Database.get())
    project_id = str(args.get("project_id", ""))
    tasks = repo.list_tasks(project_id=project_id) if project_id else repo.list_tasks()
    if not tasks:
        return "当前无任务" if not project_id else f"空间 {project_id} 中暂无任务"
    lines = [f"任务列表 ({len(tasks)} 个):" if not project_id else f"空间 {project_id} 任务列表 ({len(tasks)} 个):"]
    for task in tasks[:20]:
        extra = ""
        if task.blocked_reason:
            extra = f" [阻塞: {task.blocked_reason}]"
        if task.blocked_by_task_id:
            extra += f" [依赖: {task.blocked_by_task_id}]"
        lines.append(f"  {task.id}: [{task.status.value}] {task.title} @{task.assignee_user_id or '-'}{extra}")
    return "\n".join(lines)


def transition_task_tool(args: dict[str, Any]) -> str:
    from src.models.contracts import TaskStatus
    from src.store.database import Database
    from src.store.task_repo import TaskRepository

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


def search_tasks_tool(args: dict[str, Any]) -> str:
    from src.store.database import Database
    from src.store.task_repo import TaskRepository

    repo = TaskRepository(Database.get())
    keyword = args.get("keyword", "")
    project_id = args.get("project_id", "")
    limit = int(args.get("limit", 20))
    tasks = repo.search_tasks(keyword=keyword, project_id=project_id, limit=limit)
    if not tasks:
        return "未找到匹配的任务"
    lines = [f"搜索 '{keyword}' 找到 {len(tasks)} 条结果:"]
    for task in tasks[:limit]:
        lines.append(f"  {task.id}: [{task.status.value}] {task.title} @{task.assignee_user_id or '-'}")
    return "\n".join(lines)


def task_analytics_tool(args: dict[str, Any]) -> str:
    from src.orchestrator.task_analytics import TaskAnalytics
    from src.store.database import Database
    from src.store.task_repo import TaskRepository

    repo = TaskRepository(Database.get())
    analytics = TaskAnalytics(repo)
    space_id = args.get("project_id", "")
    data = analytics.project_stats(space_id=space_id) if space_id else analytics.dashboard_summary()
    return json.dumps(data, ensure_ascii=False, indent=2)


def work_journal_tool(args: dict[str, Any]) -> str:
    from src.agents.work_journal import WorkJournal
    from src.store.database import Database
    from src.store.task_repo import TaskRepository

    repo = TaskRepository(Database.get())
    user_id = args.get("user_id", "")
    if not user_id:
        return "请提供用户ID"
    journal = WorkJournal(repo)
    return json.dumps(journal.get_summary(user_id), ensure_ascii=False, indent=2)


def list_spaces_tool(args: dict[str, Any]) -> str:
    del args
    from src.rooms.space_registry import SpaceRegistry
    from src.store.database import Database
    from src.store.task_repo import TaskRepository

    repo = TaskRepository(Database.get())
    registry = SpaceRegistry(repo=repo)
    return json.dumps(registry.stats(), ensure_ascii=False, indent=2)


def set_priority_tool(args: dict[str, Any]) -> str:
    from src.store.database import Database
    from src.store.task_repo import TaskRepository

    repo = TaskRepository(Database.get())
    task_id = args.get("task_id", "")
    priority = args.get("priority", "medium")
    if priority not in ("high", "medium", "low"):
        return "优先级必须为 high/medium/low"
    repo.set_priority(task_id, priority)
    return f"任务 {task_id} 优先级已设为 {priority}"
