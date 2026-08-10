from __future__ import annotations

import logging
import re
import sqlite3
import time as _time

from dataclasses import dataclass
from typing import Any

from src.agents import PersonalAgent
from src.engine.base import AgentEngine
from src.gateway.dispatcher import Dispatcher, RouteKind
from src.gateway.file_message_pairing import (
    build_combined_file_message_content,
    infer_document_title,
    should_buffer_text_for_file_pairing,
    should_generate_document_from_content,
)
from src.gateway.wecom_adapter import adapt_wecom_payload
from src.memory.context_builder import MemoryContextBuilder
from src.memory.conversation import ConversationStore
from src.models import AgentResponse
from src.observability.langsmith_support import traceable_op
from src.orchestrator.batch_processor import BatchProcessor

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class InboundResult:
    route_kind: str
    target_id: str
    response: AgentResponse | None = None
    buffered_count: int = 0
    memory_context: str = ""


_file_buffer: dict[str, tuple[str, float]] = {}      # user_id -> (file_text, timestamp) — file came first
_text_buffer: dict[str, tuple[str, float]] = {}      # user_id -> (text, timestamp) — text came first
_web_search_page_cache: dict[str, tuple[str, int, float]] = {}
_PAIR_TIMEOUT = 30  # seconds to wait for the paired message
_WEB_SEARCH_PAGE_CACHE_TTL = 1800


def looks_web_ppt_search_request(text: str) -> bool:
    normalized = (text or "").strip().lower()
    if not normalized:
        return False
    wants_web = any(token in normalized for token in ("上网", "联网", "搜索", "查找", "检索", "调研"))
    wants_ppt = any(token in normalized for token in ("ppt", "pptx", "幻灯片", "演示文稿"))
    return wants_web and wants_ppt


def looks_web_research_ppt_generation_request(text: str) -> bool:
    normalized = (text or "").strip().lower()
    if not looks_web_ppt_search_request(normalized):
        return False
    leading_search = re.match(r"^(?:请)?(?:帮我|给我|替我)?(?:上网|联网)?(?:查找|搜索|检索|找)", normalized)
    if leading_search:
        return False
    generation_phrases = (
        "生成一份",
        "生成一个",
        "生成ppt",
        "生成 ppt",
        "制作一份",
        "制作一个",
        "做成ppt",
        "做成 ppt",
        "输出为ppt",
        "输出成ppt",
        "整理成ppt",
        "整理为ppt",
    )
    return any(token in normalized for token in generation_phrases)


def infer_ppt_title_from_request(text: str) -> str:
    normalized = (text or "").strip().replace("\n", " ")
    patterns = [
        r"(?:生成|制作|做成|整理成)([^，。,.]{2,60}?(?:PPT|ppt|PPTX|pptx|幻灯片|演示文稿))",
        r"(?:查找|搜索|检索|调研)([^，。,.]{2,60}?(?:总结|汇报|分析|资料))",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            title = match.group(1).strip()
            title = re.sub(r"(方面的|相关的)?(?:总结)?(?:PPTX?|pptx?|幻灯片|演示文稿)$", "", title).strip()
            if title:
                return f"{title}总结PPT"
    return "联网资料总结PPT"


def build_ppt_search_query(text: str) -> str:
    normalized = (text or "").strip()
    cleaned = re.sub(r"^(?:请)?(?:帮我|给我|替我)?(?:上网|联网)?(?:查找|搜索|检索|找)", "", normalized).strip()
    cleaned = re.sub(r"^(?:生成|制作|查找|搜索|检索)", "", cleaned).strip()
    cleaned = re.sub(r"(?:相关|方面|方面的|的)?(?:总结|汇报|分析)?(?:pptx?|PPTX?|幻灯片|演示文稿)(?:资料|文件|课件|链接)?", "", cleaned).strip()
    cleaned = re.sub(r"(?:方面的|相关的)?(?:总结|汇报|分析)$", "", cleaned).strip()
    cleaned = cleaned or normalized
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not re.search(r"\b(?:ppt|pptx)\b|课件|幻灯片|演示文稿|filetype:ppt", cleaned, flags=re.I):
        cleaned = f"{cleaned} PPT PPTX 课件 filetype:ppt OR filetype:pptx"
    return cleaned


def format_ppt_search_results(query: str, search_text: str) -> str:
    return (
        f"已按“查找已有 PPT 资料”处理，没有新生成 PPT 文件。\n\n"
        f"检索关键词：{query}\n\n"
        f"{search_text}\n\n"
        "如果你需要我把这些资料重新整理成一份新的 PPT，可以再说："
        "“基于这些资料生成一份 PPT”。"
    )


def looks_web_general_search_request(text: str) -> bool:
    normalized = (text or "").strip().lower()
    if not normalized:
        return False
    if looks_web_ppt_search_request(normalized):
        return False
    wants_web = any(token in normalized for token in ("上网", "联网", "搜索", "查找", "检索", "调研"))
    wants_reference = any(token in normalized for token in ("资料", "文献", "文章", "网页", "信息", "报告", "关于"))
    wants_generate = any(token in normalized for token in ("生成", "制作", "写一份", "整理成", "输出为", "输出成"))
    return wants_web and wants_reference and not wants_generate


def build_general_search_query(text: str) -> str:
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^(?:请)?(?:帮我|给我|替我)?(?:上网|联网)?(?:查找|搜索|检索|调研|找)", "", cleaned).strip()
    cleaned = re.sub(r"^(?:一下|下|关于|有关)", "", cleaned).strip()
    cleaned = re.sub(r"(?:相关|有关|方面的|方面)?(?:的)?(?:资料|文献|文章|网页|信息|报告)$", "", cleaned).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or (text or "").strip()


def format_general_search_results(query: str, search_text: str) -> str:
    return f"联网检索：{query}\n\n{search_text}"


def looks_web_more_request(text: str) -> bool:
    normalized = (text or "").strip().lower()
    return normalized in {"查看更多", "更多", "下一页", "继续看", "继续", "more", "next"}


def get_cached_web_search_page(user_key: str, now: float) -> tuple[str, int] | None:
    cached = _web_search_page_cache.get(user_key)
    if not cached:
        return None
    query, page, ts = cached
    if now - ts > _WEB_SEARCH_PAGE_CACHE_TTL:
        _web_search_page_cache.pop(user_key, None)
        return None
    return query, page


def set_cached_web_search_page(user_key: str, query: str, page: int, now: float) -> None:
    _web_search_page_cache[user_key] = (query, page, now)


def build_web_research_ppt_content(query: str, research_text: str) -> str:
    return "\n\n".join(
        [
            f"{query}总结",
            "一、主题背景\n基于公开资料梳理该主题的应用场景、问题边界和工程关注点。",
            "二、资料来源概览\n" + research_text[:1200],
            "三、典型缺陷类型\n围绕裂纹、蠕变、腐蚀、局部过热、材质退化、焊接或制造缺陷等方向归纳。",
            "四、原因分析框架\n从材料、工况、设计、制造、安装、运行维护和检测监测等维度分析。",
            "五、检测与诊断建议\n结合无损检测、金相分析、硬度检测、壁厚监测、运行参数趋势和失效案例复盘。",
            "六、预防和改进措施\n建立风险分级、定期检测、异常工况复盘、备件管理和寿命评估机制。",
            "七、后续工作建议\n将公开资料与企业现场历史数据、检修记录、运行参数和专家经验结合，形成内部知识库。",
        ]
    )


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

    @traceable_op("handle_wecom_payload", run_type="chain")
    def handle_wecom_payload(self, payload: dict[str, Any]) -> InboundResult:
        user_id = payload.get("from_user_id", "") or payload.get("from", "")
        now = _time.time()
        self._clear_stale_pair_buffers(now)

        # Intercept file messages: download, convert, buffer for pairing with next text
        if payload.get("msg_type") == "file" and payload.get("media_id"):
            try:
                from src.gateway.wecom_file_handler import handle_wecom_file
                file_data = handle_wecom_file(payload)
                file_text = file_data.get("summary", "")
                if file_text:
                    recent_text = self._pop_recent_text(user_id, now)
                    if recent_text:
                        payload["content"] = build_combined_file_message_content(file_text, recent_text)
                        payload["_template_path"] = file_data.get("template_path", "")
                        payload["is_file_message"] = True
                    else:
                        _file_buffer[user_id] = (file_data, now)
                        filename = file_data.get("filename") or payload.get("file_name") or payload.get("content") or "文档"
                        return InboundResult(
                            route_kind="personal",
                            target_id=user_id,
                            response=AgentResponse(text=f"已收到文件《{filename}》。请继续发送你的要求，我会结合文件内容一起处理。"),
                        )
            except Exception as e:
                logger.error("File handler error: %s", e)

        # If there's buffered file content for this user, prepend it to the message text
        if user_id in _file_buffer:
            file_data, _ = _file_buffer.pop(user_id)
            file_text = file_data.get("summary", "")
            msg_text = payload.get("content") or payload.get("text", "")
            payload["content"] = build_combined_file_message_content(file_text, msg_text)
            payload["_template_path"] = file_data.get("template_path", "")
            payload["is_file_message"] = True
        elif payload.get("msg_type") != "file":
            msg_text = payload.get("content") or payload.get("text", "")
            if should_buffer_text_for_file_pairing(msg_text):
                _text_buffer[user_id] = (msg_text, now)

        adapted = adapt_wecom_payload(payload)
        decision = self.dispatcher.route(adapted.message)

        if decision.kind == RouteKind.PERSONAL:
            user_msg = adapted.message.content
            from src.gateway.entry_links import build_entry_link_reply

            entry_reply = build_entry_link_reply(
                str(adapted.context.metadata.get("platform") or adapted.context.metadata.get("provider") or "wecom"),
                decision.target_id,
                user_msg,
            ) if not payload.get("is_file_message") else ""
            if entry_reply:
                return InboundResult(
                    route_kind=decision.kind.value,
                    target_id=decision.target_id,
                    response=AgentResponse(text=entry_reply),
                    memory_context="",
                )
            convo = self._conversations.get(decision.target_id)

            if looks_web_more_request(user_msg):
                cached = get_cached_web_search_page(decision.target_id, now)
                if cached:
                    from src.tools.web_research_service import web_search_aggregate_page

                    query, page = cached
                    next_page = page + 1
                    search_text = web_search_aggregate_page(query, page=next_page, page_size=20, max_total=80)
                    set_cached_web_search_page(decision.target_id, query, next_page, now)
                    response = AgentResponse(text=format_general_search_results(query, search_text))
                else:
                    response = AgentResponse(text="没有可继续查看的上一轮联网检索结果。请先发送“上网查找……”发起一次检索。")
                convo.add("user", user_msg)
                if response.text:
                    convo.add("assistant", response.text)
                self._conversations.save_all()
                return InboundResult(
                    route_kind=decision.kind.value,
                    target_id=decision.target_id,
                    response=response,
                    memory_context="",
                )

            if looks_web_ppt_search_request(user_msg) and not looks_web_research_ppt_generation_request(user_msg):
                from src.tools.web_research_service import web_ppt_search

                query = build_ppt_search_query(user_msg)
                search_text = web_ppt_search(query, max_results=8)
                response = AgentResponse(text=format_ppt_search_results(query, search_text))
                convo.add("user", user_msg)
                if response.text:
                    convo.add("assistant", response.text)
                self._conversations.save_all()
                return InboundResult(
                    route_kind=decision.kind.value,
                    target_id=decision.target_id,
                    response=response,
                    memory_context="",
                )

            if looks_web_research_ppt_generation_request(user_msg):
                from src.tools.builtin import _generate_report_handler
                from src.tools.web_research_service import web_search_aggregate

                title = infer_ppt_title_from_request(user_msg)
                research = web_search_aggregate(user_msg, max_results=8)
                content = build_web_research_ppt_content(title, research)
                response_text = _generate_report_handler(
                    {
                        "title": title,
                        "content": content,
                        "from": decision.target_id,
                        "format": "pptx",
                        "_skip_enrichment": True,
                        "_source_provider": adapted.context.metadata.get("provider", ""),
                        "_source_transport": adapted.context.metadata.get("transport", ""),
                    }
                )
                response = AgentResponse(text=response_text)
                convo.add("user", user_msg)
                if response.text:
                    convo.add("assistant", response.text)
                self._conversations.save_all()
                return InboundResult(
                    route_kind=decision.kind.value,
                    target_id=decision.target_id,
                    response=response,
                    memory_context="",
                )

            if looks_web_general_search_request(user_msg):
                from src.tools.web_research_service import web_search_aggregate_page

                query = build_general_search_query(user_msg)
                search_text = web_search_aggregate_page(query, page=1, page_size=20, max_total=80)
                set_cached_web_search_page(decision.target_id, query, 1, now)
                response = AgentResponse(text=format_general_search_results(query, search_text))
                convo.add("user", user_msg)
                if response.text:
                    convo.add("assistant", response.text)
                self._conversations.save_all()
                return InboundResult(
                    route_kind=decision.kind.value,
                    target_id=decision.target_id,
                    response=response,
                    memory_context="",
                )

            if payload.get("is_file_message") and should_generate_document_from_content(user_msg):
                from src.tools.builtin import _generate_report_handler
                title = infer_document_title(user_msg)
                response_text = _generate_report_handler(
                    {
                        "title": title,
                        "content": title,
                        "from": decision.target_id,
                        "format": "docx",
                        "_context_text": user_msg,
                        "_template_path": payload.get("_template_path", ""),
                        "_source_provider": adapted.context.metadata.get("provider", ""),
                        "_source_transport": adapted.context.metadata.get("transport", ""),
                    }
                )
                response = AgentResponse(text=response_text)
                if response.text:
                    convo.add("assistant", response.text)
                self._conversations.save_all()
                return InboundResult(
                    route_kind=decision.kind.value,
                    target_id=decision.target_id,
                    response=response,
                    memory_context="",
                )

            agent = self.get_or_create_agent(decision.target_id)

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
            scope_pairs = [("personal", decision.target_id)]
            if adapted.context.dept_id:
                scope_pairs.append(("department", str(adapted.context.dept_id)))
            if adapted.context.project_id:
                scope_pairs.append(("project", str(adapted.context.project_id)))
            if adapted.context.metadata.get("source_chat_id"):
                scope_pairs.append(("group", str(adapted.context.metadata.get("source_chat_id"))))
            mem_ctx = self._memory_builder.build_context(user_msg, scopes=scope_pairs)
            conv_ctx = "" if payload.get("is_file_message") else convo.get_context(max_chars=2000)

            # Inject into conversation memory
            convo.add("user", user_msg)

            try:
                response = agent.process_message(decision.target_id, user_msg, adapted.context,
                                                 memory_context=mem_ctx, conversation_context=conv_ctx)
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                logger.exception("personal message processing hit sqlite lock")
                response = AgentResponse(text="系统正在同步企业数据，刚才这条消息处理超时。请稍后再发一次，我会继续处理。")
            except Exception:
                logger.exception("personal message processing failed")
                response = AgentResponse(text="刚才处理这条消息时遇到异常，我已经记录问题。请稍后再发一次，或换一种更具体的说法重试。")

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

    def _clear_stale_pair_buffers(self, now: float) -> None:
        stale_files = [uid for uid, (_, ts) in _file_buffer.items() if now - ts > _PAIR_TIMEOUT]
        for uid in stale_files:
            del _file_buffer[uid]
        stale_texts = [uid for uid, (_, ts) in _text_buffer.items() if now - ts > _PAIR_TIMEOUT]
        for uid in stale_texts:
            del _text_buffer[uid]

    def _pop_recent_text(self, user_id: str, now: float) -> str | None:
        buffered = _text_buffer.pop(user_id, None)
        if not buffered:
            return None
        text, ts = buffered
        if now - ts > _PAIR_TIMEOUT:
            return None
        return text
