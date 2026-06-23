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

    def process_message(self, user_id: str, text: str, context: MessageContext,
                         memory_context: str = "", conversation_context: str = "") -> AgentResponse:
        if user_id != self.user_id:
            raise ValueError("personal agent user_id mismatch")
        knowledge_block = self.memory.build_context_block()
        user_name = _resolve_user_name(user_id)
        identity = f"你的微信ID(userid)：{self.user_id}。当你查询考勤、打卡等个人数据时，请用此userid调用相关工具。"
        full_knowledge = identity + "\n" + knowledge_block if knowledge_block else identity
        self.engine._latest_user_id = self.user_id
        self.engine._latest_context_metadata = dict(context.metadata or {})
        return self.engine.process_text(text, context, knowledge_prefix=full_knowledge,
                                        conversation_context=conversation_context, user_identity=user_name)
