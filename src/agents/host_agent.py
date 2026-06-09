from __future__ import annotations

import logging
from typing import Any

from src.engine.base import AgentEngine
from src.knowledge.fts_repo import FtsKnowledgeRepository
from src.store.task_repo import TaskRepository

logger = logging.getLogger(__name__)

_SUMMARIZE_PROMPT = """你是一个项目主持人 (Host Agent)。请将以下对话整理为会议纪要：

格式要求：
1. **讨论主题** — 一句话
2. **关键结论** — 最多 3 条
3. **待办事项** — 每行一条，格式：- [ ] 事项 @负责人
4. **分歧/阻塞** — 如有

对话内容：
{conversation}

请用中文输出。"""

_ACTION_PROMPT = """你是一个项目主持人。从以下对话中提取行动项 (action items)。
每个行动项一行，格式：ACTION: 事项描述 @负责人

对话：
{conversation}

只输出 ACTION: 开头的行，没有则输出 NONE。"""


class HostAgent:
    """独立主持人 agent — 会议纪要、行动项提取、讨论摘要。

    观察空间中多轮对话，生成结构化摘要和待办事项。
    """

    def __init__(self, engine: AgentEngine, repo: TaskRepository | None = None) -> None:
        self._engine = engine
        self._repo = repo

    def summarize(self, messages: list[dict[str, Any]], max_chars: int = 6000) -> str:
        conversation = _format_messages(messages, max_chars)
        if not conversation.strip():
            return "无对话内容"
        response = self._engine.send_message(_SUMMARIZE_PROMPT.format(conversation=conversation))
        return response

    def extract_actions(self, messages: list[dict[str, Any]], max_chars: int = 4000) -> list[dict[str, str]]:
        conversation = _format_messages(messages, max_chars)
        if not conversation.strip():
            return []
        response = self._engine.send_message(_ACTION_PROMPT.format(conversation=conversation))
        actions: list[dict[str, str]] = []
        for line in response.split("\n"):
            line = line.strip()
            if line.upper().startswith("ACTION:") or line.startswith("ACTION:"):
                content = line.split(":", 1)[-1].strip()
                parts = content.rsplit("@", 1)
                desc = parts[0].strip()
                assignee = parts[1].strip() if len(parts) > 1 else ""
                actions.append({"description": desc, "assignee": assignee})
        return actions

    def auto_create_drafts(self, space_id: str, messages: list[dict[str, Any]]) -> int:
        if self._repo is None:
            return 0
        actions = self.extract_actions(messages)
        count = 0
        for a in actions:
            from src.models.contracts import TaskDraft
            import json
            draft = TaskDraft(
                title=a["description"][:100],
                description=a["description"],
                project_id=space_id,
                assignee_user_id=a.get("assignee"),
                confidence=0.7,
                source_message_ids=json.dumps([m.get("id", "") for m in messages[-5:]]),
            )
            draft_id = self._repo.save_draft(draft)
            logger.info("HostAgent: auto-created draft #%s: %s", draft_id, a["description"][:50])
            count += 1
        return count


def _format_messages(messages: list[dict[str, Any]], max_chars: int) -> str:
    lines: list[str] = []
    total = 0
    for m in reversed(messages):
        sender = m.get("from_user_id", m.get("sender", "unknown"))
        content = str(m.get("content", ""))
        line = f"[{sender}]: {content}"
        if total + len(line) > max_chars:
            break
        lines.insert(0, line)
        total += len(line)
    return "\n".join(lines)
