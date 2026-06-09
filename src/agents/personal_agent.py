from __future__ import annotations

from src.engine.base import AgentEngine
from src.memory.sidecar import SidecarMemory
from src.models.contracts import AgentResponse, MessageContext


class PersonalAgent:
    """Employee-facing agent contract with sidecar memory injection."""

    def __init__(self, user_id: str, engine: AgentEngine, memory_dir: str = "") -> None:
        self.user_id = user_id
        self.engine = engine
        self.memory = SidecarMemory(user_id, base_dir=memory_dir)

    def process_message(self, user_id: str, text: str, context: MessageContext,
                         memory_context: str = "", conversation_context: str = "") -> AgentResponse:
        if user_id != self.user_id:
            raise ValueError("personal agent user_id mismatch")
        knowledge_block = self.memory.build_context_block()
        identity = f"你的微信ID(userid)是：{self.user_id}。当用户查询考勤、打卡等个人数据时，请使用此userid调用相关工具。"
        return self.engine.process_text(text, context, knowledge_prefix=knowledge_block,
                                        conversation_context=conversation_context, user_identity=identity)
