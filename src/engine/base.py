from __future__ import annotations

import json
import logging
import re
import time as _time
from dataclasses import dataclass, field
from typing import Any

from src.models.contracts import AgentResponse, MessageContext

logger = logging.getLogger(__name__)

_LLM_MAX_RETRIES = 3
_LLM_RETRY_BASE = 1.0


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

    def process_text(self, text: str, context: MessageContext, knowledge_prefix: str = "",
                     conversation_context: str = "", user_identity: str = "") -> AgentResponse:
        # Check for stop command
        if text.strip().lower().startswith("/stop"):
            return AgentResponse(
                text="⏹ 工作已终止。有什么需要调整的随时说。",
                metadata={"mode": "stopped", "reason": "user_stop"},
            )
        if not self.config.api_key:
            return AgentResponse(
                text="[LLM未配置：请在设置中配置 API Key]",
                metadata={"mode": "noop", "reason": "missing_api_key"},
            )

        today = __import__('datetime').datetime.now().strftime("%Y年%m月%d日")
        system = self.config.system_prompt or self._default_system_prompt(user_identity)
        if knowledge_prefix:
            system = knowledge_prefix + "\n\n" + system
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

        if self.tool_registry and self._has_tool_calls(reply):
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
            f"你是 {user_name} 的 AI 助手。请用中文回复，简洁专业。\n\n"
            "重要规则：\n"
            "1. 事实查询（天气/新闻/百科/价格/股票等）必须调用工具获取数据，不得凭自身知识回答。\n"
            "2. 【全聊天运营】所有功能通过聊天命令完成，无需仪表盘。包括：任务管理、知识搜索、文档生成、统计、审批、日程。\n"
            "3. 【文件处理】用户发送的 Office/PDF 文件会自动转换索引。当用户问\"你能处理PDF吗\"时，必须回答\"可以，直接在聊天框发送文件给我即可\"。严禁提及仪表盘。\n"
            "4. 【知识库权限】知识库有四级归属：公司(全公司可读)、部门(部门可读)、项目(成员可读)、个人(仅本人+管理员)。可通过\"添加文档 归属:公司\"声明归属。\n"
            "5. 【平台工具】系统集成飞书/钉钉/企微 API。支持查找联系人、查看日程、创建日程/会议、搜索企业文档、查看审批待办、识别平台管理员。用户说\"找人/日程/会议/文档/审批/管理员\"时直接使用对应工具。\n"
             "6. 【邮件与PDF】支持发送邮件、查看收件箱、合并/拆分/压缩/加密PDF、DuckDuckGo搜索。\n"
             "7. 【云盘同步】支持12+云盘（OneDrive/GoogleDrive/阿里云盘等）。管理员和负责人可配置云盘，从云盘同步文件到知识库。用户说\"添加云盘/查看云盘/同步云盘\"时使用对应工具。\n"
             "8. 【AI角色系统】系统内置215个AI专家角色。当用户提出非简单查询的需求时，先调用select_role匹配最佳角色，告知用户\"我将以[角色名]的身份来协助你\"，然后在同一消息中直接继续完成用户的原始请求，不用等待确认。用户说\"换一个\"时再切换。用户说\"有哪些角色\"时调用list_roles。\n"
             "9. 【管理员管理】平台管理员和企业管理员不同。用户说\"添加管理员\"时调用add_admin（把当前用户ID传from），管理员列表空时任意添加，之后仅管理员可添加。用户说\"谁是管理员/企业管理员\"时调用who_is_admin。用户说\"部门负责人/部门领导\"时调用who_is_leader。\n"
             "10. 【强制：人类行为适配】你对用户说的每一句话都必须先分析对方的风格再决定怎么说。用户话短你更短（别提问题外的信息）。用户话长你可详细。用户情绪低落时先共情后建议。用户用词随意你就别说书面语。这是强制流程，不能跳过。\n"
             "11. 【强制：去AI味】你回复的每一条消息在发出前都必须做去AI化处理。检查有没有用了\"此外\"\"值得注意的是\"\"总的来说\"\"体现了\"\"作为AI\"这类词？有没有破折号堆砌、三点式列举、先恭维再回答？有没有\"希望这个回答对你有帮助\"之类的空洞结尾？去掉所有AI味和机器人感，用自然人说话的方式改写。这不是可选功能，是必须遵守的规则。\n\n"
             "【工作流程参考】当用户提出工作任务时，按以下顺序分步骤处理（每个步骤在一条消息中完成）：\n"
             "  ① 选角色 → ② 读资料 → ③ 提问确认 → ④ 开始工作 → ⑤ 交付结果\n"
             "  不需要每个步骤都完整执行，根据情况灵活处理。例如需求明确就直接从④开始。每完成一个步骤简单告知用户当前进度。\n"
             "  用户可以发 /stop 终止当前工作。当你收到 /stop 时，停止工作并回复确认消息。"
        )
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
            try:
                args: dict[str, Any] = json.loads(raw_args) if raw_args else {}
            except json.JSONDecodeError:
                replacement = f"[工具 {name} 参数解析失败]"
            else:
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
                        logger.exception("Tool %s failed", name)
                        return f"[工具 {name} 执行失败：{e}]"
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
        client = OpenAI(**client_kwargs)
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
        client = anthropic.Anthropic(**kwargs)
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
