from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Protocol
from datetime import datetime, timedelta

from src.engine.base import AgentEngine
from src.models.contracts import BlockedTask, Message, MessageContext, Reminder, Task, TaskDraft, TaskStatus
from src.observability.langsmith_support import traceable_op

logger = logging.getLogger(__name__)


class SummaryBuilder(Protocol):
    def build_summary(self, project_id: str) -> str:
        ...


_TASK_ID_PROMPT = """你是一个项目助理，请分析以下项目群消息，识别出需要创建任务的条目。

规则：
1. 只识别明确的行动项、待办事项或任务
2. 返回 JSON 数组，每个元素包含：title, description, assignee_user_id(如果提到了负责人), confidence(0~1)
3. 如果没有任务需要创建，返回空数组 []
4. 请只输出 JSON，不要加额外说明"""


def _parse_task_drafts(text: str, project_id: str, source_ids: list[str]) -> list[TaskDraft]:
    text = text.strip()
    if not text or text == "[]":
        return []
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(line for line in lines if not line.startswith("```"))
    try:
        items: list[dict[str, Any]] = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("LLM task draft output not parseable: %s", text[:200])
        return []
    drafts: list[TaskDraft] = []
    for item in items:
        title = (item.get("title") or "").strip()
        if not title:
            continue
        drafts.append(
            TaskDraft(
                title=title[:80],
                description=(item.get("description") or "").strip()[:500],
                project_id=project_id,
                source_message_ids=list(source_ids),
                assignee_user_id=(item.get("assignee_user_id") or "").strip() or None,
                due_at=datetime.now() + timedelta(days=3) if not item.get("due_at") else None,
                confidence=float(item.get("confidence", 0.5)),
            )
        )
    return drafts


def _infer_assignee_from_org(project_id: str, message: Message) -> str | None:
    try:
        from src.platform.org_graph import OrgGraphService
        from src.rooms.space_registry import SpaceRegistry
        from src.store.database import Database
        from src.store.task_repo import TaskRepository

        registry = SpaceRegistry(repo=TaskRepository(Database.get()))
        record = registry.get(project_id)
        dept_id = ""
        if record and record.metadata.get("dept_id"):
            dept_id = str(record.metadata["dept_id"])
        graph = OrgGraphService()
        if record and record.members:
            for user in graph.get_users_by_ids("wecom", record.members):
                name = str(user.get("name", "")).strip()
                if name and name in message.content and user["user_id"] != message.sender_user_id:
                    return str(user["user_id"])
        for name in re.findall(r"[\u4e00-\u9fff]{2,4}", message.content):
            candidate = graph.find_user_by_name("wecom", name, dept_id=dept_id)
            if candidate and candidate != message.sender_user_id:
                return candidate
    except Exception:
        return None
    return None


class ProjectAgent:
    """Project-space agent contract for M1."""

    def __init__(self, project_id: str, engine: AgentEngine, task_repo: Any = None) -> None:
        self.project_id = project_id
        self.engine = engine
        self.task_repo = task_repo

    @traceable_op("identify_project_tasks", run_type="chain")
    def identify_tasks(self, project_id: str, messages: list[Message]) -> list[TaskDraft]:
        if project_id != self.project_id:
            raise ValueError("project agent project_id mismatch")

        # LLM-based identification when engine has API key
        if self.engine.config.api_key:
            return self._identify_via_llm(project_id, messages)

        # Heuristic fallback when no API key configured
        drafts: list[TaskDraft] = []
        for message in messages:
            if "TODO:" in message.content or "待办" in message.content:
                assignee = _infer_assignee_from_org(project_id, message) or message.sender_user_id
                drafts.append(
                    TaskDraft(
                        title=message.content[:40],
                        description=message.content,
                        project_id=project_id,
                        source_message_ids=[message.id],
                        assignee_user_id=assignee,
                        due_at=datetime.now() + timedelta(days=3),
                        confidence=0.5,
                    )
                )
        return drafts

    def _identify_via_llm(self, project_id: str, messages: list[Message]) -> list[TaskDraft]:
        if not messages:
            return []
        body = "\n---\n".join(f"[{m.sender_user_id}] {m.content}" for m in messages)
        source_ids = [m.id for m in messages]
        context = MessageContext(space_type=project_id, space_id=project_id)
        logger.info("identify_tasks for %s: %d messages via LLM", project_id, len(messages))
        response = self.engine.process_text(
            f"{_TASK_ID_PROMPT}\n\n消息：\n{body}",
            context,
        )
        drafts = _parse_task_drafts(response.text, project_id, source_ids)
        logger.info("identify_tasks result: %d drafts from %d msgs", len(drafts), len(messages))
        return drafts

    def create_draft_task(self, project_id: str, draft: TaskDraft) -> Task:
        if project_id != self.project_id:
            raise ValueError("project agent project_id mismatch")
        return Task(
            id=f"draft-{draft.source_message_ids[0]}",
            title=draft.title,
            description=draft.description,
            project_id=project_id,
            status=TaskStatus.DRAFT,
            assignee_user_id=draft.assignee_user_id,
            collaborator_ids=list(draft.collaborator_ids),
            source_message_ids=list(draft.source_message_ids),
            due_at=draft.due_at,
            metadata={"confidence": draft.confidence, **draft.metadata},
        )

    def check_blocked_tasks(self, project_id: str) -> list[BlockedTask]:
        if project_id != self.project_id:
            raise ValueError("project agent project_id mismatch")
        if self.task_repo is None:
            return []
        tasks = self.task_repo.list_tasks(project_id=project_id)
        now = datetime.now()
        blocked: list[BlockedTask] = []
        for t in tasks:
            if t.status.value in ("confirmed", "in_progress") and t.due_at:
                if t.due_at < now:
                    blocked.append(
                        BlockedTask(
                            task_id=t.id,
                            project_id=project_id,
                            reason=f"任务已逾期（截止 {t.due_at}）",
                            suggested_next_steps=["重新评估排期", "与负责人沟通进展"],
                        )
                    )
            if t.status.value == "in_progress":
                age = now - (t.metadata.get("started_at") or t.due_at or now)
                if isinstance(age, timedelta) and age.days >= 5:
                    blocked.append(
                        BlockedTask(
                            task_id=t.id,
                            project_id=project_id,
                            reason="进行中超过 5 天无进展",
                            suggested_next_steps=["确认是否遇到阻塞", "安排同步会议"],
                        )
                    )
        return blocked

    def generate_reminder(self, task_id: str, reason: str) -> Reminder:
        text = f"任务 {task_id} 需要关注：{reason}"
        return Reminder(task_id=task_id, reason=reason, text=text)

    def summarize_phase(self, project_id: str, summary_builder: SummaryBuilder) -> str:
        if project_id != self.project_id:
            raise ValueError("project agent project_id mismatch")
        return summary_builder.build_summary(project_id)
