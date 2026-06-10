from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.agents import PersonalAgent
from src.engine.base import AgentEngine
from src.gateway.dispatcher import Dispatcher, RouteKind
from src.gateway.wecom_adapter import adapt_wecom_payload
from src.memory.context_builder import MemoryContextBuilder
from src.memory.conversation import ConversationStore
from src.models import AgentResponse
from src.orchestrator.batch_processor import BatchProcessor


@dataclass(slots=True)
class InboundResult:
    route_kind: str
    target_id: str
    response: AgentResponse | None = None
    buffered_count: int = 0
    memory_context: str = ""


class InboundGatewayService:
    """Inbound pipeline with memory injection and conversation history."""

    def __init__(
        self,
        dispatcher: Dispatcher,
        batch_processor: BatchProcessor,
        personal_agents: dict[str, PersonalAgent] | None = None,
        engine: AgentEngine | None = None,
        memory_dir: str = "",
        memory_enabled: bool = True,
        warm_store: Any = None,
        cold_store: Any = None,
    ) -> None:
        self.dispatcher = dispatcher
        self.batch_processor = batch_processor
        self.personal_agents = personal_agents or {}
        self._engine = engine
        self._memory_dir = memory_dir
        self._memory_builder = MemoryContextBuilder(enabled=memory_enabled)
        self._conversations = ConversationStore(save_dir="./data/conversations",
                                                 warm_store=warm_store, cold_store=cold_store)

    def handle_wecom_payload(self, payload: dict[str, Any]) -> InboundResult:
        # Intercept file messages: download, convert, index, inject text
        if payload.get("msg_type") == "file" and payload.get("media_id"):
            try:
                from src.gateway.wecom_file_handler import handle_wecom_file
                file_text = handle_wecom_file(payload)
                if file_text:
                    payload["content"] = file_text
                    payload["is_file_message"] = True
                    # File-only messages: silently accept, don't trigger Agent response
                    # User will send text instructions in a follow-up message
                    if not payload.get("text", "").strip():
                        return InboundResult(
                            route_kind=RouteKind.PERSONAL.value,
                            target_id=payload.get("from_user_id", ""),
                            response=AgentResponse(text=""),
                        )
            except Exception as e:
                logger.error("File handler error: %s", e)

        adapted = adapt_wecom_payload(payload)
        decision = self.dispatcher.route(adapted.message)

        if decision.kind == RouteKind.PERSONAL:
            agent = self.get_or_create_agent(decision.target_id)
            user_msg = adapted.message.content
            convo = self._conversations.get(decision.target_id)

            # Handle session commands
            cmd = user_msg.strip()
            if cmd in ("/new", "/重置", "/新会话", "/newchat"):
                sid = self._conversations.new_session(decision.target_id)
                return InboundResult(route_kind=decision.kind.value, target_id=decision.target_id,
                                     response=AgentResponse(text=f"新会话 #{sid} 已开启，之前的对话已存档。输入 /sessions 查看历史。"))

            if cmd.startswith(("/session ", "/会话 ")):
                parts = cmd.split()
                if len(parts) == 2:
                    try:
                        sid = int(parts[1])
                        if self._conversations.switch_session(decision.target_id, sid):
                            return InboundResult(route_kind=decision.kind.value, target_id=decision.target_id,
                                                 response=AgentResponse(text=f"已切换到会话 #{sid}"))
                        else:
                            return InboundResult(route_kind=decision.kind.value, target_id=decision.target_id,
                                                 response=AgentResponse(text=f"会话 #{sid} 不存在。输入 /sessions 查看所有会话。"))
                    except ValueError:
                        pass

            if cmd in ("/sessions", "/会话列表", "/历史"):
                sessions = self._conversations.list_sessions(decision.target_id)
                if not sessions:
                    return InboundResult(route_kind=decision.kind.value, target_id=decision.target_id,
                                         response=AgentResponse(text="当前没有历史会话。"))
                lines = ["历史会话："]
                for s in sessions:
                    marker = " [当前]" if s["active"] else ""
                    lines.append(f"  #{s['id']} ({s['turns']} 轮对话){marker}")
                lines.append("输入 /session N 切换到某会话。")
                return InboundResult(route_kind=decision.kind.value, target_id=decision.target_id,
                                     response=AgentResponse(text="\n".join(lines)))

            if cmd in ("/archive", "/存档", "/归档"):
                mem = self._conversations._memories.get(decision.target_id)
                if mem and len(mem.to_dict()) > 0:
                    mem.save(self._conversations.save_dir)
                    self._conversations.archive_session(mem)
                    return InboundResult(route_kind=decision.kind.value, target_id=decision.target_id,
                                         response=AgentResponse(text=f"当前会话 #{mem.session_id} 已存档（{len(mem.to_dict())} 轮对话）。输入 /sessions 查看历史。"))
                return InboundResult(route_kind=decision.kind.value, target_id=decision.target_id,
                                     response=AgentResponse(text="当前会话没有内容可存档。"))

            if cmd in ("/help", "/帮助"):
                return InboundResult(route_kind=decision.kind.value, target_id=decision.target_id,
                                     response=AgentResponse(text="可用命令：\n  /new - 开启新会话\n  /archive - 存档当前会话\n  /sessions - 历史会话列表\n  /session N - 切换到会话N\n  /help - 帮助"))

            # Build memory context
            mem_ctx = self._memory_builder.build_context(user_msg)
            conv_ctx = convo.get_context(max_chars=2000)

            # Inject into conversation memory
            convo.add("user", user_msg)

            response = agent.process_message(decision.target_id, user_msg, adapted.context,
                                             memory_context=mem_ctx, conversation_context=conv_ctx)

            # Save agent's response
            if response and response.text:
                convo.add("assistant", response.text)
            self._conversations.save_all()

            return InboundResult(
                route_kind=decision.kind.value, target_id=decision.target_id,
                response=response, memory_context=mem_ctx[:200] if mem_ctx else "",
            )

        self.batch_processor.submit(adapted.message)
        buffered = len(self.batch_processor._messages_by_space.get(decision.target_id, []))
        return InboundResult(route_kind=decision.kind.value, target_id=decision.target_id, buffered_count=buffered)

    def get_or_create_agent(self, user_id: str) -> PersonalAgent:
        agent = self.personal_agents.get(user_id)
        if agent is not None:
            return agent
        if self._engine is None:
            raise KeyError(f"no personal agent for user {user_id} and no engine to create one")
        agent = PersonalAgent(user_id, self._engine, memory_dir=self._memory_dir)
        self.personal_agents[user_id] = agent
        return agent
