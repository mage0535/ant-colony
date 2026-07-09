from __future__ import annotations

import logging
from pathlib import Path

from src.engine.base import AgentEngine
from src.knowledge.contracts import KnowledgeEntry
from src.memory.sidecar import SidecarMemory
from src.models.contracts import AgentResponse, MessageContext
from src.workflows.office_workflow_service import OfficeWorkflowService

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
        self._last_knowledge_entries: list[KnowledgeEntry] = []

    def process_message(self, user_id: str, text: str, context: MessageContext,
                         memory_context: str = "", conversation_context: str = "") -> AgentResponse:
        if user_id != self.user_id:
            raise ValueError("personal agent user_id mismatch")
        knowledge_block = self.memory.build_context_block()
        user_name = _resolve_user_name(user_id)
        identity = f"你的微信ID(userid)：{self.user_id}。当你查询考勤、打卡等个人数据时，请用此userid调用相关工具。"
        prefetched_entries = _prefetch_accessible_entries(user_id, text, context)
        prefetched_knowledge = _render_prefetched_knowledge(prefetched_entries)
        if not prefetched_knowledge and _looks_knowledge_followup_query(text):
            prefetched_knowledge = self._last_knowledge_answer
            prefetched_entries = self._last_knowledge_entries
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
        workflow_response = _run_workflow_shortcut(user_id, text, context)
        if workflow_response:
            return workflow_response
        shortcut_response = _build_prefetched_answer(text, prefetched_entries, prefetched_knowledge, context)
        if shortcut_response:
            self._last_knowledge_answer = prefetched_knowledge
            self._last_knowledge_entries = list(prefetched_entries)
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


def _prefetch_accessible_entries(user_id: str, text: str, context: MessageContext) -> list[KnowledgeEntry]:
    if not text.strip() or text.strip().startswith("/"):
        return []
    try:
        from src.tools.knowledge_tools import search_knowledge_entries

        space_id = context.project_id or context.dept_id or context.space_id
        return search_knowledge_entries(text, user_id=user_id, space_id=space_id or "", limit=3)
    except Exception as exc:
        logger.warning("Knowledge prefetch failed for %s: %s", user_id, exc)
        return []

def _render_prefetched_knowledge(entries: list[KnowledgeEntry]) -> str:
    if not entries:
        return ""
    from src.tools.knowledge_tools import owner_type_label
    from src.knowledge.linking import build_knowledge_open_url

    lines = []
    for item in entries:
        title = str(item.metadata.get("title", "")).strip() or item.content.splitlines()[0][:80]
        content = item.content
        if content.startswith(title):
            content = content[len(title):].lstrip()
        lines.append(
            f"【{owner_type_label(item.owner_type.value)}知识】{title}\n"
            f"打开查看：{build_knowledge_open_url(item.id)}\n"
            f"{content[:1200]}"
        )
    return "\n\n".join(lines)


def _build_prefetched_answer(text: str, entries: list[KnowledgeEntry], prefetched_knowledge: str, context: MessageContext) -> str:
    if not prefetched_knowledge or not (_looks_knowledge_first_query(text) or _looks_knowledge_followup_query(text)):
        return ""
    if str(context.metadata.get("provider", "")) == "wecom_bot":
        bot_file = _build_bot_file_payload(entries)
        if bot_file:
            return bot_file
    return "我先从你有权限访问的知识库里找到了相关内容，你可以直接打开查看：\n\n" + prefetched_knowledge[:1500]


def _build_bot_file_payload(entries: list[KnowledgeEntry]) -> str:
    if len(entries) != 1:
        return ""
    entry = entries[0]
    source_path = str(entry.metadata.get("source_path", "")).strip()
    if not source_path:
        return ""
    resolved = Path(source_path)
    if not resolved.is_absolute():
        repo_root = Path(__file__).resolve().parents[2]
        resolved = (repo_root / source_path).resolve()
    if not resolved.is_file():
        return ""
    import json

    title = str(entry.metadata.get("title", "")).strip() or resolved.name
    return "[BOT_FILE]" + json.dumps(
        {
            "path": str(resolved),
            "filename": resolved.name,
            "caption": f"已为你推送知识库文件：{title}",
        },
        ensure_ascii=False,
    )


def _run_workflow_shortcut(user_id: str, text: str, context: MessageContext) -> AgentResponse | None:
    normalized = text.strip()
    if not normalized:
        return None
    service = OfficeWorkflowService()
    from src.platform.enterprise_query import plan_enterprise_query

    enterprise_plan = plan_enterprise_query(normalized)
    query_markers = (
        "查询",
        "查",
        "情况",
        "状态",
        "进度",
        "哪个",
        "哪些",
        "是否",
        "有人",
        "占用",
        "可用",
        "空闲",
        "到哪",
        "所有",
        "汇总",
    )
    if enterprise_plan.domains and any(marker in normalized for marker in query_markers):
        result = service.enterprise_app_query(user_id, normalized, context)
        return AgentResponse(text=result.content)
    if "审批" in normalized and any(marker in normalized for marker in ("进度", "状态", "卡", "跟踪", "催办")):
        result = service.approval_followup(user_id, normalized, context)
        return AgentResponse(text=result.content)
    if "会议" in normalized and any(marker in normalized for marker in ("安排", "组织", "议程", "纪要", "约")):
        result = service.meeting_coordination(user_id, normalized, context)
        return AgentResponse(text=result.content)
    if any(marker in normalized for marker in ("制度", "办法", "通知", "周报", "方案")) and any(marker in normalized for marker in ("起草", "生成", "整理", "草稿")):
        result = service.policy_drafting(user_id, normalized, context)
        return AgentResponse(text=result.content)
    if any(marker in normalized for marker in ("工单", "工号", "订单", "异常")) and any(marker in normalized for marker in ("查询", "分析", "看", "跟踪")):
        result = service.workorder_analysis(user_id, normalized, context)
        return AgentResponse(text=result.content)
    return None
