from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from src.models.contracts import Task as TaskModel
from src.models.contracts import TaskDraft
from src.models.contracts import TaskStatus
from src.store.database import Database
from src.web.sse_bus import emit

logger = logging.getLogger(__name__)


class TaskRepository:
    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database.get()
        self._conn = self.db.connect()

    # ---- drafts ----

    def save_draft(self, draft: TaskDraft) -> int:
        cur = self._conn.execute(
            """INSERT INTO task_drafts
               (title, description, project_id, assignee_user_id, confidence, source_message_ids)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                draft.title,
                draft.description,
                draft.project_id,
                draft.assignee_user_id,
                draft.confidence,
                json.dumps(draft.source_message_ids, ensure_ascii=False),
            ),
        )
        self._conn.commit()
        draft_id = cur.lastrowid or 0
        emit("draft_generated", draft_id=draft_id, title=draft.title, project_id=draft.project_id, assignee=draft.assignee_user_id)
        return draft_id

    def list_drafts(self, project_id: str = "", status: str = "pending") -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM task_drafts WHERE status = ? AND (? = '' OR project_id = ?) ORDER BY created_at DESC",
            (status, project_id, project_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def confirm_draft(self, draft_id: int) -> TaskModel | None:
        row = self._conn.execute(
            "SELECT * FROM task_drafts WHERE id = ? AND status = 'pending'",
            (draft_id,),
        ).fetchone()
        if not row:
            return None
        task = TaskModel(
            id=f"task-{draft_id}",
            title=row["title"],
            description=row["description"],
            project_id=row["project_id"],
            assignee_user_id=row["assignee_user_id"],
            source_message_ids=json.loads(row["source_message_ids"]),
            status=TaskStatus.CONFIRMED,
        )
        self._conn.execute("UPDATE task_drafts SET status = 'confirmed' WHERE id = ?", (draft_id,))
        self._conn.execute(
            "INSERT INTO tasks (id, title, description, project_id, assignee_user_id, source_message_ids, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                task.id,
                task.title,
                task.description,
                task.project_id,
                task.assignee_user_id,
                json.dumps(task.source_message_ids, ensure_ascii=False),
                task.status.value,
            ),
        )
        self._conn.commit()
        emit("task_created", task_id=task.id, title=task.title, project_id=task.project_id)
        return task

    def dismiss_draft(self, draft_id: int) -> None:
        self._conn.execute("UPDATE task_drafts SET status = 'dismissed' WHERE id = ?", (draft_id,))
        self._conn.commit()
        emit("draft_dismissed", draft_id=draft_id)

    def create_task(self, title: str, description: str, project_id: str,
                    assignee_user_id: str | None = None, priority: str = "medium") -> TaskModel:
        import uuid
        task = TaskModel(
            id=f"task-{uuid.uuid4().hex[:12]}",
            title=title,
            description=description,
            project_id=project_id,
            assignee_user_id=assignee_user_id,
            status=TaskStatus.CONFIRMED,
            priority=priority,
        )
        self._conn.execute(
            "INSERT INTO tasks (id, title, description, project_id, assignee_user_id, source_message_ids, status, priority) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (task.id, task.title, task.description, task.project_id, task.assignee_user_id,
             json.dumps(task.source_message_ids, ensure_ascii=False), task.status.value, task.priority),
        )
        self._conn.commit()
        emit("task_created", task_id=task.id, title=task.title, project_id=task.project_id)
        return task

    # ---- tasks ----

    def list_tasks(self, project_id: str = "") -> list[TaskModel]:
        rows = self._conn.execute(
            "SELECT * FROM tasks WHERE (? = '' OR project_id = ?) "
            "ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 WHEN 'low' THEN 2 END, created_at DESC",
            (project_id, project_id),
        ).fetchall()
        result: list[TaskModel] = []
        for r in rows:
            result.append(
                TaskModel(
                    id=r["id"],
                    title=r["title"],
                    description=r["description"],
                    project_id=r["project_id"],
                    assignee_user_id=r["assignee_user_id"],
                    collaborator_ids=json.loads(r["collaborator_ids"]),
                    source_message_ids=json.loads(r["source_message_ids"]),
                    status=TaskStatus(r["status"]),
                    due_at=datetime.fromisoformat(r["due_at"]) if r["due_at"] else None,
                    blocked_reason=r["blocked_reason"],
                    blocked_by_task_id=r["blocked_by_task_id"],
                    priority=r["priority"],
                )
            )
        return result

    def get_task(self, task_id: str) -> TaskModel | None:
        row = self._conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        return TaskModel(
            id=row["id"],
            title=row["title"],
            description=row["description"],
            project_id=row["project_id"],
            assignee_user_id=row["assignee_user_id"],
            collaborator_ids=json.loads(row["collaborator_ids"]),
            source_message_ids=json.loads(row["source_message_ids"]),
            status=TaskStatus(row["status"]),
            due_at=datetime.fromisoformat(row["due_at"]) if row["due_at"] else None,
            blocked_reason=row["blocked_reason"],
            blocked_by_task_id=row["blocked_by_task_id"],
            priority=row["priority"],
        )

    def update_task_status(self, task_id: str, status: TaskStatus, blocked_reason: str | None = None) -> None:
        self._conn.execute(
            "UPDATE tasks SET status = ?, blocked_reason = ? WHERE id = ?",
            (status.value, blocked_reason, task_id),
        )
        self._conn.commit()
        emit("task_transitioned", task_id=task_id, status=status.value, blocked_reason=blocked_reason)
        if status == TaskStatus.DONE:
            self.cascade_unblock(task_id)

    def revert_to_draft(self, task_id: str) -> None:
        row = self._conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            return
        draft_id_str = task_id.replace('task-', '') if task_id.startswith('task-') else task_id
        self._conn.execute(
            "INSERT OR IGNORE INTO task_drafts (title, description, project_id, assignee_user_id, status) "
            "VALUES (?, ?, ?, ?, 'pending')",
            (row['title'], row['description'], row['project_id'], row['assignee_user_id']),
        )
        self._conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        self._conn.commit()
        emit("draft_generated", draft_id=0, title=row['title'], project_id=row['project_id'])

    # ---- dependencies ----

    def set_dependency(self, task_id: str, blocked_by_task_id: str) -> None:
        self._conn.execute(
            "UPDATE tasks SET blocked_by_task_id = ? WHERE id = ?",
            (blocked_by_task_id, task_id),
        )
        self._conn.commit()
        emit("dependency_set", task_id=task_id, blocked_by_task_id=blocked_by_task_id)

    def get_blocked_by(self, task_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT blocked_by_task_id FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        return row["blocked_by_task_id"] if row else None

    def get_blockers_of(self, task_id: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT id FROM tasks WHERE blocked_by_task_id = ?", (task_id,)
        ).fetchall()
        return [r["id"] for r in rows]

    def cascade_unblock(self, task_id: str) -> list[str]:
        unblocked: list[str] = []
        for child_id in self.get_blockers_of(task_id):
            self._conn.execute(
                "UPDATE tasks SET blocked_by_task_id = NULL, blocked_reason = NULL, status = ? WHERE id = ?",
                (TaskStatus.CONFIRMED.value, child_id),
            )
            self._conn.commit()
            unblocked.append(child_id)
            emit("task_transitioned", task_id=child_id, status=TaskStatus.CONFIRMED.value, blocked_reason=None)
        return unblocked

    def search_tasks(self, keyword: str, project_id: str = "", limit: int = 50) -> list[TaskModel]:
        rows = self._conn.execute(
            "SELECT * FROM tasks WHERE (title LIKE ? OR description LIKE ?) AND (? = '' OR project_id = ?) ORDER BY created_at DESC LIMIT ?",
            (f"%{keyword}%", f"%{keyword}%", project_id, project_id, limit),
        ).fetchall()
        result: list[TaskModel] = []
        for r in rows:
            result.append(TaskModel(
                id=r["id"], title=r["title"], description=r["description"],
                project_id=r["project_id"], assignee_user_id=r["assignee_user_id"],
                collaborator_ids=json.loads(r["collaborator_ids"]),
                source_message_ids=json.loads(r["source_message_ids"]),
                status=TaskStatus(r["status"]),
                due_at=datetime.fromisoformat(r["due_at"]) if r["due_at"] else None,
                blocked_reason=r["blocked_reason"],
                blocked_by_task_id=r["blocked_by_task_id"],
                priority=r["priority"],
            ))
        return result

    def set_priority(self, task_id: str, priority: str) -> None:
        self._conn.execute("UPDATE tasks SET priority = ? WHERE id = ?", (priority, task_id))
        self._conn.commit()

    # ---- messages ----

    def save_message(self, space_id: str, from_user_id: str, content: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO space_messages (space_id, from_user_id, content) VALUES (?, ?, ?)",
            (space_id, from_user_id, content),
        )
        self._conn.commit()
        msg_id = cur.lastrowid or 0
        emit("message_received", message_id=msg_id, space_id=space_id, from_user=from_user_id)
        return msg_id

    def list_messages(self, space_id: str = "", limit: int = 50, keyword: str = "", since: str = "") -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []
        if space_id:
            conditions.append("space_id = ?")
            params.append(space_id)
        if keyword:
            conditions.append("content LIKE ?")
            params.append(f"%{keyword}%")
        if since:
            conditions.append("created_at >= ?")
            params.append(since)
        where = " AND ".join(conditions) if conditions else "1=1"
        rows = self._conn.execute(
            f"SELECT * FROM space_messages WHERE {where} ORDER BY id DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_messages_processed(self, space_id: str) -> None:
        self._conn.execute("UPDATE space_messages SET processed = 1 WHERE space_id = ? AND processed = 0", (space_id,))
        self._conn.commit()

    # ---- reminders ----

    def save_reminder(self, task_id: str, space_id: str, reason: str, text: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO reminders (task_id, space_id, reason, text) VALUES (?, ?, ?, ?)",
            (task_id, space_id, reason, text),
        )
        self._conn.commit()
        rid = cur.lastrowid or 0
        emit("reminder_fired", reminder_id=rid, task_id=task_id, space_id=space_id, reason=reason, text=text)
        return rid

    def list_reminders(self, space_id: str = "", include_dismissed: bool = False) -> list[dict[str, Any]]:
        if include_dismissed:
            rows = self._conn.execute(
                "SELECT * FROM reminders WHERE (? = '' OR space_id = ?) ORDER BY id DESC LIMIT 50",
                (space_id, space_id),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM reminders WHERE dismissed = 0 AND (? = '' OR space_id = ?) ORDER BY id DESC LIMIT 50",
                (space_id, space_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def dismiss_reminder(self, reminder_id: int) -> None:
        self._conn.execute("UPDATE reminders SET dismissed = 1 WHERE id = ?", (reminder_id,))
        self._conn.commit()
        emit("reminder_dismissed", reminder_id=reminder_id)

    def load_unprocessed_messages(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM space_messages WHERE processed = 0 ORDER BY created_at ASC",
        ).fetchall()
        return [dict(r) for r in rows]
