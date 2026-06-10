from __future__ import annotations

import json
import logging
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse, parse_qs

import re

from src.agents import PersonalAgent, ProjectAgent
from src.engine.factory import build_engine, build_registry
from src.gateway.card_renderer import render_task_draft_card
from src.gateway.dispatcher import Dispatcher
from src.gateway.inbound_service import InboundGatewayService
from src.guard.governance_parser import GovernanceParser
from src.models.contracts import OrchestratorAction
from src.models.contracts import TaskStatus
from src.models.task_flow import materialize_draft
from src.orchestrator.action_service import OrchestratorActionService
from src.orchestrator.batch_flusher import BatchFlusher
from src.orchestrator.batch_processor import BatchProcessor
from src.orchestrator.task_service import TaskService
from src.store.repo_adapter import SqliteTaskRepositoryAdapter
from src.store.task_repo import TaskRepository as SqliteTaskRepo

logger = logging.getLogger(__name__)

_CONFIRM_PATTERNS = {"确认", "确认任务", "confirm", "yes", "是"}
_DISMISS_PATTERNS = {"驳回", "这不是任务", "不是任务", "no", "取消", "dismiss", "reject"}
_STATUS_TRANSITION_PATTERNS = re.compile(
    r"(?P<action>开始|完成|阻塞|取消|重启|start|complete|block|cancel|resume)"
    r"(?:任务|task)?\s*"
    r"(?P<task_id>[a-zA-Z0-9_-]+)?\s*"
    r"(?:因为|due to|because)?\s*"
    r"(?P<reason>.*)",
    re.IGNORECASE,
)


class WecomWebhookHandler(BaseHTTPRequestHandler):
    request_count: int = 0
    start_time: float = time.time()
    gateway: InboundGatewayService | None = None
    sqlite_repo: SqliteTaskRepo | None = None
    task_service: TaskService | None = None
    project_agents: dict[str, ProjectAgent] | None = None
    project_engine: Any = None
    governance_parser: GovernanceParser = GovernanceParser()

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            payload: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError as e:
            self._respond(400, {"error": f"bad json: {e}"})
            return

        parsed = urlparse(self.path)
        if parsed.path == "/tasks":
            self._handle_create_task(payload)
            return

        if self.gateway is None:
            self._respond(503, {"error": "gateway not initialized"})
            return

        try:
            result = self.gateway.handle_wecom_payload(payload)
            body: dict[str, Any] = {
                "route_kind": result.route_kind,
                "target_id": result.target_id,
            }

            if self.sqlite_repo is not None:
                from_user = payload.get("from") or payload.get("from_user_id", "unknown")
                raw_content = payload.get("content") or payload.get("text") or payload.get("text_content", "")
                self.sqlite_repo.save_message(result.target_id, str(from_user), str(raw_content))

            if result.route_kind == "space_batch" and self.sqlite_repo is not None:
                space_id = result.target_id
                content = payload.get("content") or payload.get("text", "")
                cmd = self.governance_parser.parse(content)
                if cmd:
                    body["governance_command"] = cmd.kind

                if content.strip() in _CONFIRM_PATTERNS:
                    confirmed = self._confirm_pending(space_id)
                    if confirmed:
                        body["confirmed"] = confirmed

                if content.strip() in _DISMISS_PATTERNS:
                    dismissed = self._dismiss_pending(space_id)
                    if dismissed:
                        body["dismissed"] = dismissed

                transition = self._handle_task_status_transition(space_id, content)
                if transition:
                    body["task_transition"] = transition

                drafts = self.sqlite_repo.list_drafts(project_id=space_id, status="pending")
                if drafts:
                    body["pending_drafts"] = len(drafts)

            if result.route_kind == "personal" and self.gateway is not None:
                user_id = result.target_id
                content = payload.get("content") or payload.get("text", "")
                memory_reply = self._handle_memory_command(user_id, content)
                if memory_reply:
                    body["reply"] = memory_reply
                    result.response = None
                elif result.response and result.response.text:
                    body["reply"] = result.response.text
            elif result.response and result.response.text:
                body["reply"] = result.response.text
            if result.buffered_count:
                body["buffered"] = result.buffered_count
            self._respond(200, body)
        except Exception as e:
            logger.exception("webhook handler error")
            self._respond(500, {"error": str(e)})

    def _confirm_pending(self, space_id: str) -> list[dict[str, Any]]:
        if self.sqlite_repo is None or self.task_service is None:
            return []
        drafts = self.sqlite_repo.list_drafts(project_id=space_id, status="pending")
        results = []
        for d in drafts:
            task = self.sqlite_repo.confirm_draft(d["id"])
            if task:
                results.append({"task_id": task.id, "title": task.title})
                logger.info("Chat-confirmed task %s: %s", task.id, task.title)
        return results

    def _dismiss_pending(self, space_id: str) -> list[int]:
        if self.sqlite_repo is None:
            return []
        drafts = self.sqlite_repo.list_drafts(project_id=space_id, status="pending")
        ids = [d["id"] for d in drafts]
        for did in ids:
            self.sqlite_repo.dismiss_draft(did)
            logger.info("Chat-dismissed draft #%s", did)
        return ids

    _ACTION_MAP = {
        "开始": TaskStatus.IN_PROGRESS,
        "完成": TaskStatus.DONE,
        "阻塞": TaskStatus.BLOCKED,
        "取消": TaskStatus.CANCELLED,
        "启动": TaskStatus.IN_PROGRESS,
        "重启": TaskStatus.IN_PROGRESS,
        "start": TaskStatus.IN_PROGRESS,
        "complete": TaskStatus.DONE,
        "block": TaskStatus.BLOCKED,
        "cancel": TaskStatus.CANCELLED,
        "resume": TaskStatus.IN_PROGRESS,
    }

    def _handle_task_status_transition(self, space_id: str, content: str) -> dict[str, Any] | None:
        if self.sqlite_repo is None:
            return None
        content_stripped = content.strip()
        m = _STATUS_TRANSITION_PATTERNS.match(content_stripped)
        if not m:
            return None
        action_key = m.group("action").lower()
        target = self._ACTION_MAP.get(action_key)
        if target is None:
            return None
        task_id = m.group("task_id")
        reason = m.group("reason").strip() if m.group("reason") else None

        if task_id:
            self.sqlite_repo.update_task_status(task_id, target, blocked_reason=reason)
            r = {"task_id": task_id, "status": target.value, "action": action_key}
            if reason:
                r["reason"] = reason
            return r

        tasks = self.sqlite_repo.list_tasks(project_id=space_id)
        for t in tasks:
            if target == TaskStatus.IN_PROGRESS and t.status == TaskStatus.CONFIRMED:
                self.sqlite_repo.update_task_status(t.id, target)
                return {"task_id": t.id, "title": t.title, "status": target.value, "action": action_key}
            if target == TaskStatus.DONE and t.status == TaskStatus.IN_PROGRESS:
                self.sqlite_repo.update_task_status(t.id, target)
                return {"task_id": t.id, "title": t.title, "status": target.value, "action": action_key}
            if target == TaskStatus.BLOCKED and t.status == TaskStatus.IN_PROGRESS:
                self.sqlite_repo.update_task_status(t.id, target, blocked_reason=reason)
                r = {"task_id": t.id, "title": t.title, "status": target.value, "action": action_key}
                if reason:
                    r["reason"] = reason
                return r
            if target == TaskStatus.CANCELLED and t.status in (TaskStatus.CONFIRMED, TaskStatus.IN_PROGRESS):
                self.sqlite_repo.update_task_status(t.id, target)
                return {"task_id": t.id, "title": t.title, "status": target.value, "action": action_key}
        return None

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/drafts":
            self._handle_list_drafts(parse_qs(parsed.query))
        elif parsed.path == "/blocked":
            self._handle_list_blocked(parse_qs(parsed.query))
        elif parsed.path == "/tasks":
            self._handle_list_tasks(parse_qs(parsed.query))
        elif parsed.path == "/messages":
            self._handle_list_messages(parse_qs(parsed.query))
        elif parsed.path == "/reminders":
            self._handle_list_reminders(parse_qs(parsed.query))
        elif parsed.path == "/health":
            uptime = time.time() - WecomWebhookHandler.start_time
            active = 0
            if self.sqlite_repo:
                active = len(self.sqlite_repo.list_tasks())
            self._respond(200, {
                "status": "healthy",
                "service": "ant-colony-gateway",
                "uptime_seconds": round(uptime, 1),
                "request_count": WecomWebhookHandler.request_count,
                "active_tasks": active,
                "db": "ok" if self.sqlite_repo else "unavailable",
            })
        elif parsed.path == "/metrics":
            uptime = time.time() - WecomWebhookHandler.start_time
            self._respond(200, {
                "gateway_uptime_seconds": round(uptime, 1),
                "gateway_requests_total": WecomWebhookHandler.request_count,
                "gateway_requests_per_second": round(WecomWebhookHandler.request_count / max(uptime, 1), 2),
            })
        else:
            self._respond(200, {"status": "ok", "service": "ant-colony-gateway"})

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            payload: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError as e:
            self._respond(400, {"error": f"bad json: {e}"})
            return
        if parsed.path == "/confirm":
            self._handle_confirm(payload)
        elif parsed.path == "/dismiss":
            self._handle_dismiss(payload)
        elif parsed.path == "/transition":
            self._handle_transition(payload)
        elif parsed.path == "/reminder/dismiss":
            self._handle_dismiss_reminder(payload)
        else:
            self._respond(404, {"error": "not found"})

    def _handle_list_tasks(self, params: dict[str, list[str]]) -> None:
        if self.sqlite_repo is None:
            self._respond(500, {"error": "not initialized"})
            return
        project_id = params.get("space_id", [""])[0]
        tasks = self.sqlite_repo.list_tasks(project_id=project_id)
        serialized = []
        for t in tasks:
            serialized.append({
                "id": t.id,
                "title": t.title,
                "project_id": t.project_id,
                "assignee_user_id": t.assignee_user_id,
                "status": t.status.value,
                "due_at": t.due_at.isoformat() if t.due_at else None,
                "blocked_reason": t.blocked_reason,
            })
        self._respond(200, {"tasks": serialized})

    def _handle_list_blocked(self, params: dict[str, list[str]]) -> None:
        if self.project_agents is None:
            self._respond(500, {"error": "not initialized"})
            return
        space_id = params.get("space_id", [""])[0]
        results: list[dict[str, Any]] = []
        for sid, agent in self.project_agents.items():
            if space_id and sid != space_id:
                continue
            try:
                blocked = agent.check_blocked_tasks(sid)
                for b in blocked:
                    reminder = agent.generate_reminder(b.task_id, b.reason)
                    results.append({
                        "space_id": sid,
                        "task_id": b.task_id,
                        "reason": b.reason,
                        "suggested_next_steps": b.suggested_next_steps,
                        "reminder": reminder.text,
                    })
            except Exception:
                logger.exception("Blocked check for %s", sid)
        self._respond(200, {"blocked": results})

    def _handle_list_messages(self, params: dict[str, list[str]]) -> None:
        if self.sqlite_repo is None:
            self._respond(500, {"error": "not initialized"})
            return
        space_id = params.get("space_id", [""])[0]
        keyword = params.get("q", [""])[0] or params.get("keyword", [""])[0]
        since = params.get("since", [""])[0]
        limit_s = params.get("limit", ["50"])[0]
        try:
            limit = int(limit_s)
        except ValueError:
            limit = 50
        messages = self.sqlite_repo.list_messages(space_id=space_id, limit=limit, keyword=keyword, since=since)
        self._respond(200, {"messages": messages})

    def _handle_list_reminders(self, params: dict[str, list[str]]) -> None:
        if self.sqlite_repo is None:
            self._respond(500, {"error": "not initialized"})
            return
        space_id = params.get("space_id", [""])[0]
        reminders = self.sqlite_repo.list_reminders(space_id=space_id)
        self._respond(200, {"reminders": reminders})

    def _handle_dismiss_reminder(self, payload: dict[str, Any]) -> None:
        if self.sqlite_repo is None:
            self._respond(500, {"error": "not initialized"})
            return
        reminder_id = payload.get("reminder_id")
        if not reminder_id:
            self._respond(400, {"error": "reminder_id required"})
            return
        self.sqlite_repo.dismiss_reminder(reminder_id)
        self._respond(200, {"reminder_id": reminder_id, "status": "dismissed"})

    def _handle_list_drafts(self, params: dict[str, list[str]]) -> None:
        if self.sqlite_repo is None:
            self._respond(500, {"error": "task_repo not initialized"})
            return
        project_id = params.get("space_id", [""])[0]
        drafts = self.sqlite_repo.list_drafts(project_id=project_id, status="pending")
        self._respond(200, {"drafts": drafts})

    def _handle_confirm(self, payload: dict[str, Any]) -> None:
        if self.sqlite_repo is None:
            self._respond(500, {"error": "task_repo not initialized"})
            return
        draft_id = payload.get("draft_id")
        if not draft_id:
            self._respond(400, {"error": "draft_id required"})
            return
        task = self.sqlite_repo.confirm_draft(draft_id)
        if task is None:
            self._respond(404, {"error": "draft not found or already confirmed"})
            return
        self._respond(200, {"task_id": task.id, "title": task.title, "status": "confirmed"})

    def _handle_dismiss(self, payload: dict[str, Any]) -> None:
        if self.sqlite_repo is None:
            self._respond(500, {"error": "task_repo not initialized"})
            return
        draft_id = payload.get("draft_id")
        if not draft_id:
            self._respond(400, {"error": "draft_id required"})
            return
        self.sqlite_repo.dismiss_draft(draft_id)
        self._respond(200, {"draft_id": draft_id, "status": "dismissed"})

    def _handle_create_task(self, payload: dict[str, Any]) -> None:
        if self.sqlite_repo is None:
            self._respond(500, {"error": "not initialized"})
            return
        title = payload.get("title", "").strip()
        project_id = payload.get("project_id", "").strip()
        if not title or not project_id:
            self._respond(400, {"error": "title and project_id are required"})
            return
        task = self.sqlite_repo.create_task(
            title=title,
            description=payload.get("description", ""),
            project_id=project_id,
            assignee_user_id=payload.get("assignee_user_id"),
        )
        self._respond(201, {
            "task_id": task.id,
            "title": task.title,
            "project_id": task.project_id,
            "assignee_user_id": task.assignee_user_id,
            "status": task.status.value,
        })

    def _handle_transition(self, payload: dict[str, Any]) -> None:
        if self.sqlite_repo is None:
            self._respond(500, {"error": "not initialized"})
            return
        task_id = payload.get("task_id")
        status = payload.get("status", "")
        reason = payload.get("blocked_reason")
        if not task_id or not status:
            self._respond(400, {"error": "task_id and status required"})
            return
        target = TaskStatus(status)
        self.sqlite_repo.update_task_status(task_id, target, blocked_reason=reason)
        self._respond(200, {
            "task_id": task_id,
            "status": target.value,
            "action": "transition",
            "reason": reason or "",
        })

    _MEMORY_SET_RE = re.compile(
        r"(?:设置?|我的|更新)\s*(?:我的\s*)?(角色|部门|职责|偏好|responsibilities|role|department)\s*(?:是|=|为|包括|：|:)\s*(.+)",
        re.IGNORECASE,
    )

    def _handle_memory_command(self, user_id: str, content: str) -> str | None:
        if self.gateway is None:
            return None
        m = self._MEMORY_SET_RE.match(content.strip())
        if not m:
            return None
        key_map = {"角色": "role", "部门": "department", "职责": "responsibilities", "偏好": "preferences"}
        key = key_map.get(m.group(1).lower(), m.group(1).lower())
        value = m.group(2).strip().strip("。，,.")
        agent = self.gateway.get_or_create_agent(user_id)
        agent.memory.set(key, value)
        logger.info("Memory updated for user %s: %s = %s", user_id, key, value)
        return f"已更新你的{key}为：{value}"

    def _respond(self, code: int, data: dict[str, Any]) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        WecomWebhookHandler.request_count += 1
        logger.info("webhook: %s", fmt % args)


def serve(host: str = "0.0.0.0", port: int = 18090, profile_id: str = "server-deepseek") -> None:
    engine = build_engine("personal", profile_id=profile_id)
    project_engine = build_engine("project", profile_id=profile_id)
    dispatcher = Dispatcher()
    batch = BatchProcessor()
    registry = build_registry()
    sqlite_repo = SqliteTaskRepo()
    adapter = SqliteTaskRepositoryAdapter(sqlite_repo)
    task_service = TaskService(adapter)
    action_service = OrchestratorActionService(task_service)

    from src.store.database import Database
    from src.memory.warm_store import WarmMemoryStore
    from src.memory.cold_store import ColdKnowledgeGraph
    db = Database.get()
    conn = db.connect()
    warm_store = WarmMemoryStore(conn)
    cold_store = ColdKnowledgeGraph(conn)

    gateway = InboundGatewayService(
        dispatcher=dispatcher,
        batch_processor=batch,
        personal_agents={},
        engine=engine,
        memory_dir="./data/memory",
        warm_store=warm_store,
        cold_store=cold_store,
    )

    def on_flush_actions(actions: list[OrchestratorAction]) -> None:
        for action in actions:
            if action.kind == "task_draft_identified":
                draft = action.payload.get("draft")
                if draft:
                    draft_id = sqlite_repo.save_draft(draft)
                    # Auto-confirm high confidence drafts
                    task = sqlite_repo.confirm_draft(draft_id)
                    if task:
                        logger.info("Draft #%s auto-confirmed: %s", draft_id, draft.title)
                    else:
                        logger.info("Draft #%s saved (pending confirm): %s", draft_id, draft.title)

    recovered = sqlite_repo.load_unprocessed_messages()
    for msg in recovered:
        from src.models.contracts import Message as MsgModel
        m = MsgModel(
            id=f"recovered-{msg['id']}",
            space_id=msg["space_id"],
            sender_user_id=msg["from_user_id"],
            content=msg["content"],
        )
        batch.submit(m)
        sqlite_repo.mark_messages_processed(msg["space_id"])
    if recovered:
        logger.info("Recovered %d unprocessed messages into buffer", len(recovered))

    project_agents: dict[str, ProjectAgent] = {}
    flusher = BatchFlusher(
        batch_processor=batch,
        project_agents=project_agents,
        engine=project_engine,
        interval_seconds=30.0,
        min_batch_size=2,
        on_actions=on_flush_actions,
        task_repo=sqlite_repo,
    )
    flusher.start()

    WecomWebhookHandler.gateway = gateway
    WecomWebhookHandler.sqlite_repo = sqlite_repo
    WecomWebhookHandler.task_service = task_service
    WecomWebhookHandler.project_agents = project_agents
    WecomWebhookHandler.project_engine = project_engine
    server = ThreadingHTTPServer((host, port), WecomWebhookHandler)

    logger.info("gateway webhook on %s:%s (flusher=%ss, threaded, status transitions)", host, port, flusher.interval_seconds)

    # Ensure callback service is running (auto-recover if systemd restart limit was hit)
    try:
        import subprocess as _sp
        _sp.run(["systemctl", "is-active", "--quiet", "ant-colony-callback"], check=True)
    except Exception:
        logger.warning("ant-colony-callback is down — restarting it")
        _sp.run(["sudo", "systemctl", "restart", "ant-colony-callback"], capture_output=True, timeout=15)

    # Start platform adapters (Feishu/DingTalk/Telegram) if configured
    try:
        from src.gateway.platform_adapters import start_platform_adapters
        adapter_threads = start_platform_adapters()
        if adapter_threads:
            logger.info("Started %d platform adapter(s)", len(adapter_threads))
    except Exception as e:
        logger.warning("Platform adapters not available: %s", e)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        flusher.stop()
        server.server_close()
        sqlite_repo.db.close()
        logger.info("gateway stopped")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    serve()
