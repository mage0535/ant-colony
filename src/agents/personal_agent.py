from __future__ import annotations

import logging

from src.engine.base import AgentEngine
from src.memory.sidecar import SidecarMemory
from src.models.contracts import AgentResponse, MessageContext

logger = logging.getLogger(__name__)

_user_name_cache: dict[str, str] = {}


def _resolve_user_name(user_id: str) -> str:
    if user_id in _user_name_cache:
        return _user_name_cache[user_id]
    try:
        from src.platform.api_wecom import _get
        user = _get("user/get", f"userid={user_id}")
        name = user.get("name", "") or user_id
        _user_name_cache[user_id] = name
        return name
    except Exception:
        return user_id


class PersonalAgent:
    def __init__(self, user_id: str, engine: AgentEngine, memory_dir: str = "") -> None:
        self.user_id = user_id
        self.engine = engine
        self.memory = SidecarMemory(user_id, base_dir=memory_dir)
        self._last_knowledge_answer = ""

    def process_message(self, user_id: str, text: str, context: MessageContext,
                         memory_context: str = "", conversation_context: str = "") -> AgentResponse:
        if user_id != self.user_id:
            raise ValueError("personal agent user_id mismatch")
        knowledge_block = self.memory.build_context_block()
        user_name = _resolve_user_name(user_id)
        identity = f"你的微信ID(userid)：{self.user_id}。当你查询考勤、打卡等个人数据时，请用此userid调用相关工具。"
        prefetched_knowledge = _prefetch_accessible_knowledge(user_id, text, context)
        if not prefetched_knowledge and _looks_knowledge_followup_query(text):
            prefetched_knowledge = self._last_knowledge_answer
        full_knowledge = identity + "\n" + knowledge_block if knowledge_block else identity
        if prefetched_knowledge:
            full_knowledge = (
                full_knowledge
                + "\n\n## 权限内知识库预检索结果\n"
                + prefetched_knowledge
                + "\n\n请优先基于以上本地知识库内容回答，不要在已有答案时改用互联网搜索。"
            )
        self.engine._latest_user_id = self.user_id
        self.engine._latest_context_metadata = dict(context.metadata or {})
        self.engine._latest_context_metadata["knowledge_prefetched"] = bool(prefetched_knowledge)
        shortcut_response = _build_prefetched_answer(text, prefetched_knowledge)
        if shortcut_response:
            self._last_knowledge_answer = prefetched_knowledge
            return AgentResponse(text=shortcut_response)
        return self.engine.process_text(text, context, knowledge_prefix=full_knowledge,
                                        conversation_context=conversation_context, user_identity=user_name)


def _looks_knowledge_first_query(text: str) -> bool:
    markers = ("怎么", "如何", "步骤", "操作", "说明书", "指南", "制度", "办法", "规定", "流程", "激活", "权限", "知识库")
    return any(marker in text for marker in markers)


def _looks_knowledge_followup_query(text: str) -> bool:
    normalized = text.strip()
    followups = ("具体内容", "详细内容", "引导我操作", "具体步骤", "详细步骤", "继续", "展开", "怎么做", "详细说说")
    return any(item in normalized for item in followups)


def _prefetch_accessible_knowledge(user_id: str, text: str, context: MessageContext) -> str:
    if not text.strip() or text.strip().startswith("/"):
        return ""
    try:
        from src.tools.knowledge_tools import search_knowledge_entries
        from src.tools.knowledge_tools import owner_type_label

        space_id = context.project_id or context.dept_id or context.space_id
        results = search_knowledge_entries(text, user_id=user_id, space_id=space_id or "", limit=3)
        if not results:
            return ""
        lines = []
        for item in results:
            title = str(item.metadata.get("title", "")).strip() or item.content.splitlines()[0][:80]
            content = item.content
            if content.startswith(title):
                content = content[len(title):].lstrip()
            lines.append(f"【{owner_type_label(item.owner_type.value)}知识】{title}\n{content[:1200]}")
        return "\n\n".join(lines)
    except Exception as exc:
        logger.warning("Knowledge prefetch failed for %s: %s", user_id, exc)
        return ""


def _build_prefetched_answer(text: str, prefetched_knowledge: str) -> str:
    if not prefetched_knowledge or not (_looks_knowledge_first_query(text) or _looks_knowledge_followup_query(text)):
        return ""
    return "我先从你有权限访问的知识库里找到了相关内容：\n\n" + prefetched_knowledge[:1500]
