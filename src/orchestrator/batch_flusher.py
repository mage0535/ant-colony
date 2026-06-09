from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from src.agents.project_agent import ProjectAgent
from src.engine.base import AgentEngine
from src.gateway.wecom_outbound import send_text
from src.models.contracts import Message, OrchestratorAction
from src.orchestrator.batch_processor import BatchProcessor
from src.orchestrator.task_orchestrator import TaskOrchestrator

logger = logging.getLogger(__name__)


class BatchFlusher:
    """Periodically flush buffered space messages through TaskOrchestrator.

    Runs a background thread that drains each space's messages every
    ``interval_seconds`` and emits actions via the ``on_actions`` callback.
    ProjectAgents are auto-created for unknown space IDs.
    """

    def __init__(
        self,
        batch_processor: BatchProcessor,
        project_agents: dict[str, ProjectAgent],
        engine: AgentEngine,
        interval_seconds: float = 30.0,
        min_batch_size: int = 1,
        on_actions: Callable[[list[OrchestratorAction]], None] | None = None,
        task_repo: Any = None,
    ) -> None:
        self.batch_processor = batch_processor
        self.project_agents = project_agents
        self._engine = engine
        self.interval_seconds = interval_seconds
        self.min_batch_size = min_batch_size
        self.on_actions = on_actions
        self._task_repo = task_repo
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("BatchFlusher started (interval=%ss, min_batch=%s)", self.interval_seconds, self.min_batch_size)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("BatchFlusher stopped")

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._flush_all()
            self._check_blocked()
            self._stop.wait(self.interval_seconds)

    def _check_blocked(self) -> None:
        if self._task_repo is None:
            return
        for space_id, agent in self.project_agents.items():
            try:
                blocked = agent.check_blocked_tasks(space_id)
                if blocked:
                    logger.info("Space %s: %d blocked tasks", space_id, len(blocked))
                    for b in blocked:
                        reminder = agent.generate_reminder(b.task_id, b.reason)
                        rid = self._task_repo.save_reminder(b.task_id, space_id, b.reason, reminder.text)
                        logger.info("  Reminder #%s for %s: %s", rid, b.task_id, reminder.text)
                        self._notify_assignee(b.task_id, reminder.text)
            except Exception:
                logger.exception("Blocked check failed for space %s", space_id)

    def _notify_assignee(self, task_id: str, reminder_text: str) -> None:
        if self._task_repo is None:
            return
        try:
            task = self._task_repo.get_task(task_id)
            if task and task.assignee_user_id:
                text = f"[任务提醒] {reminder_text}"
                if send_text(task.assignee_user_id, text):
                    logger.info("  WeCom notified %s for task %s", task.assignee_user_id, task_id)
        except Exception:
            pass

    def _flush_all(self) -> None:
        space_ids = self.batch_processor.space_ids()
        for space_id in space_ids:
            if space_id not in self.project_agents:
                agent = ProjectAgent(space_id, self._engine, task_repo=self._task_repo)
                self.project_agents[space_id] = agent
                logger.info("Auto-created ProjectAgent for space %s", space_id)
            project_agent = self.project_agents[space_id]
            messages = self.batch_processor.drain(space_id)
            if len(messages) < self.min_batch_size:
                if messages:
                    self.batch_processor._messages_by_space[space_id] = messages
                continue
            try:
                actions = self._process_batch(space_id, project_agent, messages)
                if actions and self.on_actions:
                    self.on_actions(actions)
            except Exception:
                logger.exception("BatchFlusher failed for space %s", space_id)

    def _process_batch(
        self, space_id: str, project_agent: ProjectAgent, messages: list[Message]
    ) -> list[OrchestratorAction]:
        orchestrator = TaskOrchestrator(project_agent)
        actions = orchestrator.on_batch(space_id, messages)
        if actions:
            logger.info("Space %s: %d actions from %d messages", space_id, len(actions), len(messages))
        return actions
