from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from src.agents import PersonalAgent, ProjectAgent
from src.engine import AgentEngine, AgentEngineConfig
from src.models import Message, MessageContext, SpaceType


class TestAgentEngine(unittest.TestCase):
    def test_no_api_key_returns_hint(self) -> None:
        config = AgentEngineConfig(model_name="test", agent_role="personal", api_key="")
        engine = AgentEngine(config)
        context = MessageContext(space_type=SpaceType.DEPARTMENT, space_id="d1")
        response = engine.process_text("hello", context)
        self.assertIn("LLM未配置", response.text)

    @patch("openai.OpenAI")
    def test_openai_provider(self, mock_openai: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.chat.completions.create.return_value.choices[0].message.content = "Hello from OpenAI"

        config = AgentEngineConfig(
            model_name="gpt-4o-mini",
            agent_role="test",
            provider="openai",
            api_key="sk-test",
        )
        engine = AgentEngine(config)
        context = MessageContext(space_type=SpaceType.DEPARTMENT, space_id="d1")
        response = engine.process_text("say hi", context)

        self.assertEqual(response.text, "Hello from OpenAI")
        self.assertEqual(response.metadata["model"], "gpt-4o-mini")
        self.assertEqual(response.metadata["provider"], "openai")

        mock_client.chat.completions.create.assert_called_once()
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        self.assertEqual(call_kwargs["model"], "gpt-4o-mini")
        self.assertEqual(len(call_kwargs["messages"]), 2)
        self.assertEqual(call_kwargs["messages"][1]["role"], "user")
        self.assertEqual(call_kwargs["messages"][1]["content"], "say hi")

    @patch("openai.OpenAI")
    def test_openai_with_custom_base_url(self, mock_openai: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.chat.completions.create.return_value.choices[0].message.content = "ok"

        config = AgentEngineConfig(
            model_name="deepseek-chat",
            agent_role="test",
            provider="openai",
            api_key="sk-ds-test",
            api_base="https://api.deepseek.com/v1",
        )
        engine = AgentEngine(config)
        context = MessageContext(space_type=SpaceType.DEPARTMENT, space_id="d1")
        response = engine.process_text("ping", context)

        self.assertEqual(response.text, "ok")
        mock_openai.assert_called_once_with(api_key="sk-ds-test", base_url="https://api.deepseek.com/v1")

    @patch("anthropic.Anthropic")
    def test_anthropic_provider(self, mock_anthropic: MagicMock) -> None:
        mock_client = MagicMock()
        mock_anthropic.return_value = mock_client

        mock_msg = MagicMock()
        mock_text_block = MagicMock()
        mock_text_block.type = "text"
        mock_text_block.text = "Hello from Claude"
        mock_msg.content = [mock_text_block]
        mock_client.messages.create.return_value = mock_msg

        config = AgentEngineConfig(
            model_name="claude-sonnet-4-20250514",
            agent_role="test",
            provider="anthropic",
            api_key="sk-ant-test",
        )
        engine = AgentEngine(config)
        context = MessageContext(space_type=SpaceType.DEPARTMENT, space_id="d1")
        response = engine.process_text("say hi", context)

        self.assertEqual(response.text, "Hello from Claude")
        self.assertEqual(response.metadata["provider"], "anthropic")

        mock_client.messages.create.assert_called_once()
        call_kwargs = mock_client.messages.create.call_args[1]
        self.assertEqual(call_kwargs["model"], "claude-sonnet-4-20250514")
        self.assertEqual(call_kwargs["messages"][0]["role"], "user")
        self.assertEqual(call_kwargs["messages"][0]["content"], "say hi")

    @patch("openai.OpenAI")
    def test_openai_api_error(self, mock_openai: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.chat.completions.create.side_effect = Exception("API timeout")

        config = AgentEngineConfig(
            model_name="gpt-4o-mini",
            agent_role="test",
            provider="openai",
            api_key="sk-test",
        )
        engine = AgentEngine(config)
        context = MessageContext(space_type=SpaceType.DEPARTMENT, space_id="d1")
        response = engine.process_text("hello", context)

        self.assertIn("LLM 调用失败", response.text)
        self.assertIn("API timeout", response.text)

    def test_system_prompt_uses_agent_role(self) -> None:
        config = AgentEngineConfig(model_name="test", agent_role="项目经理", api_key="sk-test")
        engine = AgentEngine(config)
        system = engine._default_system_prompt()
        self.assertIn("项目经理", system)

    def test_custom_system_prompt(self) -> None:
        config = AgentEngineConfig(
            model_name="test", agent_role="test", api_key="sk-test", system_prompt="You are a helpful bot."
        )
        engine = AgentEngine(config)
        self.assertEqual(engine.config.system_prompt, "You are a helpful bot.")


class TestProjectAgentTaskIdentification(unittest.TestCase):
    def test_heuristic_fallback_no_api_key(self) -> None:
        config = AgentEngineConfig(model_name="test", agent_role="project", api_key="")
        engine = AgentEngine(config)
        agent = ProjectAgent("proj-1", engine)

        messages = [
            Message(id="m1", space_id="proj-1", sender_user_id="u1", content="TODO: follow up on design"),
            Message(id="m2", space_id="proj-1", sender_user_id="u2", content="normal chat message"),
            Message(id="m3", space_id="proj-1", sender_user_id="u3", content="这个需要待办处理"),
        ]
        drafts = agent.identify_tasks("proj-1", messages)

        self.assertEqual(len(drafts), 2)
        self.assertIn("TODO:", drafts[0].title)
        self.assertIn("待办", drafts[1].title)

    @patch("openai.OpenAI")
    def test_llm_identifies_tasks(self, mock_openai: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        llm_output = json.dumps([
            {"title": "完成设计评审", "description": "u1 提出了设计评审需求", "assignee_user_id": "u1", "confidence": 0.9},
            {"title": "修复登录 bug", "description": "u2 报告了登录问题", "confidence": 0.7},
        ])
        mock_client.chat.completions.create.return_value.choices[0].message.content = llm_output

        config = AgentEngineConfig(
            model_name="gpt-4o-mini",
            agent_role="project",
            provider="openai",
            api_key="sk-test",
        )
        engine = AgentEngine(config)
        agent = ProjectAgent("proj-1", engine)

        messages = [
            Message(id="m1", space_id="proj-1", sender_user_id="u1", content="我们需要在下周前完成设计评审"),
            Message(id="m2", space_id="proj-1", sender_user_id="u2", content="登录页面有个bug需要修复"),
        ]
        drafts = agent.identify_tasks("proj-1", messages)

        self.assertEqual(len(drafts), 2)
        self.assertEqual(drafts[0].title, "完成设计评审")
        self.assertEqual(drafts[0].assignee_user_id, "u1")
        self.assertEqual(drafts[0].confidence, 0.9)
        self.assertEqual(drafts[1].title, "修复登录 bug")
        self.assertIsNone(drafts[1].assignee_user_id)

    @patch("openai.OpenAI")
    def test_llm_returns_empty(self, mock_openai: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.chat.completions.create.return_value.choices[0].message.content = "[]"

        config = AgentEngineConfig(
            model_name="gpt-4o-mini",
            agent_role="project",
            provider="openai",
            api_key="sk-test",
        )
        engine = AgentEngine(config)
        agent = ProjectAgent("proj-1", engine)

        messages = [
            Message(id="m1", space_id="proj-1", sender_user_id="u1", content="今天天气不错"),
        ]
        drafts = agent.identify_tasks("proj-1", messages)

        self.assertEqual(len(drafts), 0)

    @patch("openai.OpenAI")
    def test_llm_returns_malformed_json(self, mock_openai: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.chat.completions.create.return_value.choices[0].message.content = "不是JSON格式"

        config = AgentEngineConfig(
            model_name="gpt-4o-mini",
            agent_role="project",
            provider="openai",
            api_key="sk-test",
        )
        engine = AgentEngine(config)
        agent = ProjectAgent("proj-1", engine)

        messages = [
            Message(id="m1", space_id="proj-1", sender_user_id="u1", content="修复这个bug"),
        ]
        drafts = agent.identify_tasks("proj-1", messages)

        self.assertEqual(len(drafts), 0)

    @patch("openai.OpenAI")
    def test_llm_output_with_code_fence(self, mock_openai: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        llm_output = "```\n" + json.dumps([{"title": "测试任务", "confidence": 0.8}]) + "\n```"
        mock_client.chat.completions.create.return_value.choices[0].message.content = llm_output

        config = AgentEngineConfig(
            model_name="gpt-4o-mini",
            agent_role="project",
            provider="openai",
            api_key="sk-test",
        )
        engine = AgentEngine(config)
        agent = ProjectAgent("proj-1", engine)

        drafts = agent.identify_tasks("proj-1", [
            Message(id="m1", space_id="proj-1", sender_user_id="u1", content="请测试"),
        ])

        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0].title, "测试任务")

    def test_empty_messages(self) -> None:
        config = AgentEngineConfig(model_name="test", agent_role="project", api_key="sk-test")
        engine = AgentEngine(config)
        agent = ProjectAgent("proj-1", engine)
        drafts = agent.identify_tasks("proj-1", [])
        self.assertEqual(len(drafts), 0)

    def test_project_id_mismatch(self) -> None:
        config = AgentEngineConfig(model_name="test", agent_role="project", api_key="")
        engine = AgentEngine(config)
        agent = ProjectAgent("proj-1", engine)
        with self.assertRaises(ValueError):
            agent.identify_tasks("proj-2", [])


class TestPersonalAgent(unittest.TestCase):
    @patch("openai.OpenAI")
    def test_personal_agent_uses_engine(self, mock_openai: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.chat.completions.create.return_value.choices[0].message.content = "你好，我是你的 AI 助手"

        config = AgentEngineConfig(
            model_name="gpt-4o-mini",
            agent_role="personal",
            provider="openai",
            api_key="sk-test",
        )
        engine = AgentEngine(config)
        agent = PersonalAgent("u1", engine)
        context = MessageContext(space_type=SpaceType.DEPARTMENT, space_id="dept-1", dept_id="dept-1")

        response = agent.process_message("u1", "你好", context)

        self.assertEqual(response.text, "你好，我是你的 AI 助手")
        self.assertTrue(response.visible_to_user)

    def test_personal_agent_prefers_prefetched_knowledge_for_how_to_queries(self) -> None:
        config = AgentEngineConfig(
            model_name="gpt-4o-mini",
            agent_role="personal",
            provider="openai",
            api_key="sk-test",
        )
        engine = AgentEngine(config)
        agent = PersonalAgent("u1", engine)
        context = MessageContext(space_type=SpaceType.DEPARTMENT, space_id="dept-1", dept_id="dept-1")

        from src.knowledge.contracts import KnowledgeEntry, KnowledgeOwnerType

        entry = KnowledgeEntry(
            id="company-guide-wecom-activation",
            owner_type=KnowledgeOwnerType.ORGANIZATION,
            owner_id="*",
            content="企业微信 AI 助手激活说明书\n\n第一步 打开企业微信\n第二步 找到机器人",
            tags=["guide"],
            metadata={"title": "企业微信 AI 助手激活说明书"},
        )

        with patch(
            "src.agents.personal_agent._prefetch_accessible_entries",
            return_value=[entry],
        ):
            response = agent.process_message("u1", "我想让其他同事也激活类似你的员工企微机器人，应该怎么操作", context)

        self.assertIn("我先从你有权限访问的知识库里找到了相关内容", response.text)
        self.assertIn("企业微信 AI 助手激活说明书", response.text)
        self.assertIn("打开查看", response.text)
        self.assertIn("第一步 打开企业微信", response.text)

    def test_personal_agent_uses_last_knowledge_for_followup_question(self) -> None:
        config = AgentEngineConfig(
            model_name="gpt-4o-mini",
            agent_role="personal",
            provider="openai",
            api_key="sk-test",
        )
        engine = AgentEngine(config)
        agent = PersonalAgent("u1", engine)
        context = MessageContext(space_type=SpaceType.DEPARTMENT, space_id="dept-1", dept_id="dept-1")

        from src.knowledge.contracts import KnowledgeEntry, KnowledgeOwnerType

        entry = KnowledgeEntry(
            id="company-guide-wecom-activation",
            owner_type=KnowledgeOwnerType.ORGANIZATION,
            owner_id="*",
            content="企业微信 AI 助手激活说明书\n\n第一步 打开企业微信\n第二步 找到机器人",
            tags=["guide"],
            metadata={"title": "企业微信 AI 助手激活说明书"},
        )

        with patch(
            "src.agents.personal_agent._prefetch_accessible_entries",
            side_effect=[[entry], []],
        ):
            first = agent.process_message("u1", "我要激活ai机器人", context)
            second = agent.process_message("u1", "引导我操作", context)

        self.assertIn("企业微信 AI 助手激活说明书", first.text)
        self.assertIn("第一步 打开企业微信", second.text)

    def test_personal_agent_returns_bot_file_for_single_knowledge_file_on_wecom(self) -> None:
        config = AgentEngineConfig(
            model_name="gpt-4o-mini",
            agent_role="personal",
            provider="openai",
            api_key="sk-test",
        )
        engine = AgentEngine(config)
        agent = PersonalAgent("u1", engine)
        from src.knowledge.contracts import KnowledgeEntry, KnowledgeOwnerType
        context = MessageContext(
            space_type=SpaceType.DEPARTMENT,
            space_id="dept-1",
            dept_id="dept-1",
            metadata={"provider": "wecom_bot"},
        )

        entry = KnowledgeEntry(
            id="company-guide-wecom-activation",
            owner_type=KnowledgeOwnerType.ORGANIZATION,
            owner_id="*",
            content="企业微信 AI 助手激活说明书\n\n正文",
            tags=["guide"],
            metadata={"title": "企业微信 AI 助手激活说明书", "source_path": "docs/wecom-ai-assistant-activation-guide.md"},
        )

        with patch("src.agents.personal_agent._prefetch_accessible_entries", return_value=[entry]), \
             patch("pathlib.Path.is_file", return_value=True):
            response = agent.process_message("u1", "我要激活ai机器人", context)

        self.assertTrue(response.text.startswith("[BOT_FILE]"))
        self.assertIn("企业微信 AI 助手激活说明书", response.text)

    def test_personal_agent_routes_approval_tracking_to_bounded_enterprise_query(self) -> None:
        config = AgentEngineConfig(
            model_name="gpt-4o-mini",
            agent_role="personal",
            provider="openai",
            api_key="sk-test",
        )
        engine = AgentEngine(config)
        agent = PersonalAgent("u1", engine)
        context = MessageContext(space_type=SpaceType.DEPARTMENT, space_id="dept-1", dept_id="dept-1")

        with patch("src.agents.personal_agent.OfficeWorkflowService.enterprise_app_query", return_value=type("Result", (), {"content": "审批跟踪结果"})()):
            response = agent.process_message("u1", "帮我跟踪一下付款审批进度", context)

        self.assertEqual(response.text, "审批跟踪结果")

    def test_personal_agent_shortcuts_to_enterprise_app_query(self) -> None:
        config = AgentEngineConfig(
            model_name="gpt-4o-mini",
            agent_role="personal",
            provider="openai",
            api_key="sk-test",
        )
        engine = AgentEngine(config)
        agent = PersonalAgent("u1", engine)
        context = MessageContext(space_type=SpaceType.DEPARTMENT, space_id="dept-1", dept_id="dept-1", metadata={"provider": "wecom"})

        with patch("src.agents.personal_agent.OfficeWorkflowService.enterprise_app_query", return_value=type("Result", (), {"content": "三号会议室查询结果"})()):
            response = agent.process_message("u1", "三号会议室有人申请吗？", context)

        self.assertEqual(response.text, "三号会议室查询结果")

    def test_personal_agent_routes_personal_approval_query_to_enterprise_apps(self) -> None:
        config = AgentEngineConfig(
            model_name="gpt-4o-mini",
            agent_role="personal",
            provider="openai",
            api_key="sk-test",
        )
        agent = PersonalAgent("u1", AgentEngine(config))
        context = MessageContext(
            space_type=SpaceType.DEPARTMENT,
            space_id="dept-1",
            metadata={"provider": "wecom"},
        )
        with patch(
            "src.agents.personal_agent.OfficeWorkflowService.enterprise_app_query",
            return_value=type("Result", (), {"content": "我的审批状态"})(),
        ):
            response = agent.process_message("u1", "查询我所有审批的状态", context)

        self.assertEqual(response.text, "我的审批状态")

    def test_plain_workshop_question_is_not_forced_into_enterprise_apps(self) -> None:
        from src.agents.personal_agent import _run_workflow_shortcut

        context = MessageContext(
            space_type=SpaceType.DEPARTMENT,
            space_id="dept-1",
            metadata={"provider": "wecom"},
        )

        self.assertIsNone(_run_workflow_shortcut("u1", "目前车间通行是什么情况", context))

    def test_personal_agent_shortcuts_to_workorder_workflow(self) -> None:
        config = AgentEngineConfig(
            model_name="gpt-4o-mini",
            agent_role="personal",
            provider="openai",
            api_key="sk-test",
        )
        engine = AgentEngine(config)
        agent = PersonalAgent("u1", engine)
        context = MessageContext(space_type=SpaceType.DEPARTMENT, space_id="dept-1", dept_id="dept-1")

        with patch("src.agents.personal_agent.OfficeWorkflowService.workorder_analysis", return_value=type("Result", (), {"content": "工单分析结果"})()):
            response = agent.process_message("u1", "分析工单 WO-1001 的异常", context)

        self.assertEqual(response.text, "工单分析结果")


class TestToolCalling(unittest.TestCase):
    def test_tool_call_regex_match(self) -> None:
        text = "查时间 <tool_call>builtin:now()</tool_call>"
        from src.engine.base import _TOOL_CALL_RE
        match = _TOOL_CALL_RE.search(text)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "builtin:now")
        self.assertEqual(match.group(2), "")

    def test_tool_call_with_args(self) -> None:
        text = '<tool_call>builtin:echo({"text": "hello"})</tool_call>'
        from src.engine.base import _TOOL_CALL_RE
        match = _TOOL_CALL_RE.search(text)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "builtin:echo")
        self.assertIn("hello", match.group(2))

    def test_engine_executes_tool_call(self) -> None:
        from src.tools.registry import FusionToolRegistry
        from src.tools.builtin import register_builtin_tools

        registry = FusionToolRegistry()
        register_builtin_tools(registry)

        config = AgentEngineConfig(model_name="test", agent_role="personal", api_key="sk-test")
        engine = AgentEngine(config, tool_registry=registry)

        result = engine._execute_tool_calls("<tool_call>builtin:now({})</tool_call>")
        self.assertRegex(result, r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")

    def test_engine_unregistered_tool(self) -> None:
        from src.tools.registry import FusionToolRegistry

        registry = FusionToolRegistry()
        config = AgentEngineConfig(model_name="test", agent_role="personal", api_key="sk-test")
        engine = AgentEngine(config, tool_registry=registry)

        result = engine._execute_tool_calls('<tool_call>unknown_tool({})</tool_call>')
        self.assertIn("未注册", result)

    def test_engine_tool_call_with_bad_json(self) -> None:
        from src.tools.registry import FusionToolRegistry
        from src.tools.builtin import register_builtin_tools

        registry = FusionToolRegistry()
        register_builtin_tools(registry)

        config = AgentEngineConfig(model_name="test", agent_role="personal", api_key="sk-test")
        engine = AgentEngine(config, tool_registry=registry)

        result = engine._execute_tool_calls("<tool_call>builtin:echo(bad json)</tool_call>")
        self.assertIn("参数解析失败", result)

    def test_no_tool_calls_passthrough(self) -> None:
        config = AgentEngineConfig(model_name="test", agent_role="personal", api_key="sk-test")
        engine = AgentEngine(config)

        result = engine._execute_tool_calls("普通文本，没有工具调用")
        self.assertEqual(result, "普通文本，没有工具调用")

    def test_tool_injection_in_system_prompt(self) -> None:
        from src.tools.registry import FusionToolRegistry
        from src.tools.builtin import register_builtin_tools

        registry = FusionToolRegistry()
        register_builtin_tools(registry)

        config = AgentEngineConfig(model_name="test", agent_role="personal", api_key="sk-test")
        engine = AgentEngine(config, tool_registry=registry)

        prompt = engine._inject_tools("你是助手")
        self.assertIn("可用工具", prompt)
        self.assertIn("builtin:now", prompt)
        self.assertIn("<tool_call>", prompt)

    def test_builtin_tools_registered(self) -> None:
        from src.tools.registry import FusionToolRegistry
        from src.tools.builtin import register_builtin_tools

        registry = FusionToolRegistry()
        register_builtin_tools(registry)

        personal_tools = registry.get_for_agent("personal")
        self.assertGreaterEqual(len(personal_tools), 2)

        project_tools = registry.get_for_agent("project")
        self.assertGreaterEqual(len(project_tools), 3)
