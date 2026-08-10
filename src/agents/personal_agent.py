from __future__ import annotations

import logging
from pathlib import Path

from src.engine.base import AgentEngine
from src.knowledge.contracts import KnowledgeEntry
from src.memory.sidecar import SidecarMemory
from src.models.contracts import AgentResponse, MessageContext
from src.agents.phase1_shortcuts import run_phase1_shortcut
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
        platform = str((context.metadata or {}).get("provider") or (context.metadata or {}).get("platform") or "wecom")
        knowledge_block = self.memory.build_context_block()
        user_name = _resolve_user_name(user_id)
        from src.platform.assistant_profile_service import (
            build_profile_status_reply,
            extract_profile_request,
            get_assistant_profile,
            get_or_create_onboarding,
            save_assistant_profile,
        )

        onboarding = get_or_create_onboarding(platform=platform, user_id=user_id, user_name=user_name)
        requested_profile = extract_profile_request(text)
        if requested_profile:
            profile = save_assistant_profile(platform=platform, user_id=user_id, **requested_profile)
            call_name = str(profile.get("user_call_name") or "").strip()
            call_text = f"我会称呼你为“{call_name}”。" if call_name else ""
            return AgentResponse(text=f"好的，以后你可以叫我“{profile['assistant_name']}”。{call_text}我会优先以“{profile['role_name']}”的方式协助你；需要时也会自动调用其他合适的专业能力。")
        onboarding_message = str(onboarding.get("message") or "") if onboarding["is_first_conversation"] else ""
        profile = get_assistant_profile(platform=platform, user_id=user_id) or onboarding
        if _looks_assistant_profile_status_query(text):
            return _append_onboarding(AgentResponse(text=build_profile_status_reply(profile)), onboarding_message)
        identity = (
            f"你的企业 IM 用户 ID：{self.user_id}。当你查询考勤、打卡等个人数据时，请用此用户 ID 调用相关工具。"
            f"你是用户专属的企业 AI 助手，名字是“{profile.get('assistant_name', '企业 AI 助手')}”，"
            f"当前常用角色是“{profile.get('role_name', '通用助手')}”。"
            f"如果用户设置了称呼“{profile.get('user_call_name', '')}”，在自然合适时使用该称呼。所有面向用户的回复必须使用中文。"
        )
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
            return _append_onboarding(workflow_response, onboarding_message)
        phase1_response = run_phase1_shortcut(user_id, text, context)
        if phase1_response:
            return _append_onboarding(phase1_response, onboarding_message)
        shortcut_response = _build_prefetched_answer(text, prefetched_entries, prefetched_knowledge, context)
        if shortcut_response:
            self._last_knowledge_answer = prefetched_knowledge
            self._last_knowledge_entries = list(prefetched_entries)
            return _append_onboarding(AgentResponse(text=shortcut_response), onboarding_message)
        response = self.engine.process_text(text, context, knowledge_prefix=full_knowledge,
                                            conversation_context=conversation_context, user_identity=user_name)
        return _append_onboarding(response, onboarding_message)


def _append_onboarding(response: AgentResponse, onboarding_message: str) -> AgentResponse:
    if not onboarding_message:
        return response
    return AgentResponse(text=f"{response.text}\n\n---\n{onboarding_message}")


def _looks_assistant_profile_status_query(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    asks_name = any(token in normalized for token in ("你叫什么", "你的名字", "你叫啥", "怎么称呼你", "助手名字", "AI助手名字", "ai助手名字"))
    asks_role = any(token in normalized for token in ("当前角色", "什么角色", "你的角色", "常用角色", "你是什么身份", "你能扮演"))
    asks_call_name = any(token in normalized for token in ("你怎么称呼我", "你叫我什么", "对我的称呼", "称呼我什么"))
    return asks_name or asks_role or asks_call_name


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
        results = search_knowledge_entries(text, user_id=user_id, space_id=space_id or "", limit=3)
        if results:
            return results
        if _looks_operation_help_query(text):
            for fallback_query in (
                "企业 AI 助手使用总入口",
                "企业微信 AI 助手功能与操作说明书",
                "企业微信 AI 助手激活说明书",
            ):
                fallback = search_knowledge_entries(fallback_query, user_id=user_id, space_id=space_id or "", limit=3)
                if fallback:
                    return fallback
        return []
    except Exception as exc:
        logger.warning("Knowledge prefetch failed for %s: %s", user_id, exc)
        return []


def _looks_operation_help_query(text: str) -> bool:
    markers = (
        "不会",
        "怎么用",
        "如何用",
        "如何操作",
        "怎么操作",
        "操作方法",
        "使用方法",
        "使用说明",
        "说明书",
        "指南",
        "第一步",
        "第二步",
        "后台",
        "知识库",
        "上传",
        "激活",
        "没回复",
        "不回复",
        "没有反应",
        "打不开",
    )
    normalized = text.strip()
    return any(marker in normalized for marker in markers)

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
    extra = ""
    if _looks_operation_help_query(text):
        extra = (
            "\n\n如果你是想看一步一步的操作说明，"
            "可以继续发送“搜索知识库 企业 AI 助手使用总入口”或“搜索知识库 企业微信 AI 助手功能与操作说明书”。"
        )
    return "我先从你有权限访问的知识库里找到了相关内容，你可以直接打开查看：\n\n" + prefetched_knowledge[:1500] + extra


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
