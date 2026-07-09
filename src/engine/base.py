from __future__ import annotations

import json
import logging
import re
import time as _time
from dataclasses import dataclass, field
from typing import Any

from src.models.contracts import AgentResponse, MessageContext
from src.observability.langsmith_support import wrap_anthropic_client, wrap_openai_client

logger = logging.getLogger(__name__)

_LLM_MAX_RETRIES = 3
_LLM_RETRY_BASE = 1.0
_TOOL_CALL_RE = re.compile(r"<tool_call>([^(\s]+)\((.*?)\)</tool_call>", re.DOTALL)


def _retry_llm(fn, max_retries: int = _LLM_MAX_RETRIES) -> str:
    last_error = ""
    for attempt in range(1, max_retries + 1):
        try:
            return fn()
        except Exception as e:
            last_error = str(e)
            if attempt < max_retries:
                delay = _LLM_RETRY_BASE * (2 ** (attempt - 1))
                logger.warning("LLM call attempt %d/%d failed: %s, retrying in %.1fs",
                               attempt, max_retries, last_error, delay)
                _time.sleep(delay)
    logger.error("LLM call failed after %d attempts: %s", max_retries, last_error)
    return f"[LLM 调用失败：{last_error}]"


def _extract_tool_calls(text: str) -> list[tuple[str, str]]:
    """Extract tool calls by finding <tool_call>...</tool_call> boundaries."""
    results: list[tuple[str, str]] = []
    pos = 0
    tag_open = "<tool_call>"
    tag_close = "</tool_call>"
    while True:
        start = text.find(tag_open, pos)
        if start == -1:
            break
        end = text.find(tag_close, start)
        if end == -1:
            break
        body = text[start + len(tag_open):end]
        paren = body.find("(")
        if paren == -1:
            pos = end + len(tag_close)
            continue
        name = body[:paren].strip()
        args_raw = body[paren + 1:].rstrip()
        if args_raw.endswith(")"):
            args_raw = args_raw[:-1]
        results.append((name, args_raw.strip()))
        pos = end + len(tag_close)
    return results


def _lenient_parse_args(name: str, raw_args: str) -> dict[str, Any]:
    """Parse tool args with fallback: try JSON first, then regex extraction."""
    if not raw_args:
        return {}
    try:
        return json.loads(raw_args)
    except (json.JSONDecodeError, ValueError):
        pass
    args: dict[str, Any] = {}
    _escaped = re.sub(r'(?<!\\)"', '', raw_args)  # very rough: remove unescaped quotes
    for key in ("title", "content", "format", "from", "query", "assignee",
                "project_id", "description", "priority", "task_id", "user_id"):
        m = re.search(rf'"{key}"\s*:\s*"((?:\\.|[^"\\])*)"', raw_args, re.UNICODE)
        if m:
            val = m.group(1)
            val = val.replace('\\"', '"').replace('\\n', '\n').replace('\\\\', '\\')
            args[key] = val
            continue
        m2 = re.search(rf'"{key}"\s*:\s*([^,}}]+)', raw_args)
        if m2:
            v = m2.group(1).strip().strip('"').strip("'")
            args[key] = v
    if not args and raw_args.count('"') >= 2 and raw_args.replace('"', '', 1).find('"') > 0:
        args["content"] = raw_args
    return args


@dataclass(slots=True)
class AgentEngineConfig:
    model_name: str
    agent_role: str
    provider: str = "openai"
    api_key: str = ""
    api_base: str = ""
    max_tokens: int = 4096
    system_prompt: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class AgentEngine:
    def __init__(self, config: AgentEngineConfig, tool_registry: Any = None) -> None:
        self.config = config
        self.tool_registry = tool_registry
        self._latest_user_text = ""
        self._latest_user_id = ""
        self._latest_context_metadata: dict[str, Any] = {}

    def process_text(self, text: str, context: MessageContext, knowledge_prefix: str = "",
                     conversation_context: str = "", user_identity: str = "") -> AgentResponse:
        # Check for stop command
        if text.strip().lower().startswith("/stop"):
            return AgentResponse(
                text="⏹ 工作已终止。有什么需要调整的随时说。",
                metadata={"mode": "stopped", "reason": "user_stop"},
            )
        self._latest_user_text = text
        if not self.config.api_key:
            return AgentResponse(
                text="[LLM未配置：请在设置中配置 API Key]",
                metadata={"mode": "noop", "reason": "missing_api_key"},
            )

        today = __import__('datetime').datetime.now().strftime("%Y年%m月%d日")
        system = self.config.system_prompt or self._default_system_prompt(user_identity)
        if knowledge_prefix:
            system = knowledge_prefix + "\n\n" + system
        # Auto-inject role content based on user's text (Hermes-style skill loading)
        try:
            _role_text = self._load_matching_role(text)
            if _role_text:
                system = _role_text + "\n\n" + system
        except Exception:
            pass
        system = f"今天是{today}。{system}"
        if self.tool_registry:
            system = self._inject_tools(system)
        if conversation_context:
            system = system + "\n\n## 最近对话历史\n" + conversation_context

        provider = (self.config.provider or "openai").lower().strip()

        if provider == "anthropic":
            reply = self._call_anthropic(system, text)
        else:
            reply = self._call_openai(system, text)

        import sys as _sys2
        has_tc = self.tool_registry and self._has_tool_calls(reply)
        print("[ENGINE] LLM reply len=%d tool_call=%s first100=%s" % (
            len(reply), has_tc, reply[:100].replace("\n", "\\n")[:100]
        ), file=_sys2.stderr, flush=True)

        if has_tc:
            reply = self._execute_tool_calls(reply)

        return AgentResponse(
            text=reply,
            metadata={
                "model": self.config.model_name,
                "provider": provider,
                "agent_role": self.config.agent_role,
            },
        )

    def _default_system_prompt(self, user_identity: str = "") -> str:
        user_name = user_identity or self.config.agent_role or "员工"
        return (
            f"你是 {user_name} 的 AI 助手。\n\n"
            "工作方式：\n"
            "1. 先理解用户需求。用户可能用任何方式表达：文件、文字、模板都可以。\n"
            "2. 理解后用下方工具完成任务。用户要求生成文档时，用generate_report生成docx并推送。\n"
            "3. 调用generate_report时content只写简短概述（如'车间通行管理规定'），from填@你的用户名。系统自动从对话历史提取并丰富完整文档内容。\n"
            "4. 用户可随时发/stop终止。回复去掉AI味（此外/值得注意的是/总的来说/作为AI这类词）。\n"
            "5. 用户请求打开页面入口（后台、管理、控制台、知识库、上传文档等）时，使用get_entry_link工具生成链接。用户说'后台'、'知识库'、'管理页面'、'开通助手'等意图时都调用此工具。"
        )

    def _load_matching_role(self, text: str) -> str:
        """Auto-load relevant role content based on user's text (Hermes-style)."""
        try:
            from src.platform.role_manager import search_roles, _load_role_file
            results = search_roles(text, limit=1)
            if results:
                content = _load_role_file(results[0].name)
                if content:
                    return f"## 专家角色：{results[0].name}\n{content[:2500]}"
        except Exception:
            pass
        return ""

    def _inject_tools(self, system: str) -> str:
        tools = self.tool_registry.get_for_agent(self.config.agent_role)
        if not tools:
            return system
        lines = ["\n\n可用工具："]
        for t in tools:
            lines.append(f"- {t.name}（{t.id}）：{t.description}")
            if t.parameters:
                lines.append(f"  参数：{json.dumps(t.parameters, ensure_ascii=False)}")
        lines.append("\n如需使用工具，请在回复中包含 <tool_call>工具名({json参数})</tool_call>")
        lines.append("例如：<tool_call>builtin:now()</tool_call>")
        return system + "\n".join(lines)

    def _has_tool_calls(self, text: str) -> bool:
        return bool(_extract_tool_calls(text))

    def _execute_tool_calls(self, text: str) -> str:
        calls = _extract_tool_calls(text)
        if not calls:
            return text
        result = text
        tools = self.tool_registry.get_for_agent(self.config.agent_role)
        for name, raw_args in calls:
            args: dict[str, Any] = _lenient_parse_args(name, raw_args) if raw_args else {}
            if raw_args and not args and raw_args.strip() not in ("", "{}"):
                replacement = "[参数解析失败]"
                result = result.replace(
                    f"<tool_call>{name}({raw_args})</tool_call>",
                    replacement,
                )
                continue
            if name.endswith("generate_document"):
                import sys as _sys
                print("[BASE] generate_document: content_len=%d, from=%s, latest_user_id=%s" % (
                    len(args.get("content", "").strip()),
                    args.get("from", "(not set)"),
                    getattr(self, "_latest_user_id", "(attr missing)"),
                ), file=_sys.stderr, flush=True)
                if len(args.get("content", "").strip()) < 100:
                    args["_context_text"] = getattr(self, "_latest_user_text", text)
                if not args.get("from"):
                    args["from"] = getattr(self, "_latest_user_id", "")
                meta = getattr(self, "_latest_context_metadata", {}) or {}
                if meta.get("provider"):
                    args["_source_provider"] = meta.get("provider")
                if meta.get("transport"):
                    args["_source_transport"] = meta.get("transport")
                print("[BASE] after inject: from=%s" % args.get("from"), file=_sys.stderr, flush=True)
            elif not args.get("from"):
                uid = getattr(self, "_latest_user_id", "")
                args["from"] = uid
                if not args.get("user_id"):
                    args["user_id"] = uid
            replacement = self._dispatch_tool(name, args, tools)
            result = result.replace(
                f"<tool_call>{name}({raw_args})</tool_call>",
                replacement,
            )
        return result

    def _dispatch_tool(self, name: str, args: dict[str, Any], tools: list) -> str:
        for t in tools:
            # Match by full ID, name, or short name (without builtin: prefix)
            if t.id == name or t.name == name or t.id.endswith(":" + name):
                if t.handler:
                    try:
                        return t.handler(args)
                    except Exception as e:
                        import traceback
                        tb = traceback.format_exc()
                        logger.exception("Tool %s failed", name)
                        return f"[工具 {name} 执行失败：{e}]\n{tb}"
                return f"[工具 {name} 无处理器]"
        return f"[工具 {name} 未注册]"

    def _call_openai(self, system: str, user_text: str) -> str:
        from openai import OpenAI

        kwargs = {"api_key": self.config.api_key}
        if self.config.api_base:
            kwargs["base_url"] = self.config.api_base

        return _retry_llm(lambda: self._openai_inner(kwargs, system, user_text))

    def _openai_inner(self, client_kwargs: dict, system: str, user_text: str) -> str:
        from openai import OpenAI
        client = wrap_openai_client(OpenAI(**client_kwargs))
        resp = client.chat.completions.create(
            model=self.config.model_name or "gpt-4o-mini",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_text},
            ],
            max_tokens=self.config.max_tokens,
        )
        return self._humanize_response(resp.choices[0].message.content or "")

    def _humanize_response(self, text: str) -> str:
        """Post-process every LLM response to remove AI patterns and add natural voice."""
        if not text:
            return text
        try:
            from src.tools.humanizer import humanize
            return humanize(text)
        except Exception:
            return text

    def _call_anthropic(self, system: str, user_text: str) -> str:
        return _retry_llm(lambda: self._anthropic_inner(system, user_text))

    def _anthropic_inner(self, system: str, user_text: str) -> str:
        import anthropic
        kwargs = {"api_key": self.config.api_key}
        client = wrap_anthropic_client(anthropic.Anthropic(**kwargs))
        resp = client.messages.create(
            model=self.config.model_name or "claude-sonnet-4-20250514",
            max_tokens=self.config.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_text}],
        )
        parts = []
        for block in resp.content:
            if block.type == "text":
                parts.append(block.text)
        return self._humanize_response("\n".join(parts))
