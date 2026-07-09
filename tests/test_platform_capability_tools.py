from __future__ import annotations

import unittest
from unittest.mock import patch


class TestPlatformCapabilityTools(unittest.TestCase):
    def test_doc_search_tool_validates_query(self) -> None:
        from src.tools.platform_capability_tools import doc_search_tool

        self.assertEqual(doc_search_tool({"query": ""}), "请提供搜索关键词")

    def test_doc_search_tool_delegates_to_platform(self) -> None:
        from src.tools.platform_capability_tools import doc_search_tool

        with patch("src.tools.knowledge_tools.search_knowledge_tool", return_value="未找到关于 '制度' 的知识条目"), \
             patch("src.platform.invoke_capability", return_value="doc-result") as mock_invoke:
            result = doc_search_tool({"query": "制度"})

        self.assertEqual(mock_invoke.call_args.args[:2], ("docs.search", "制度"))
        self.assertEqual(result, "doc-result")

    def test_doc_search_tool_prefers_local_knowledge(self) -> None:
        from src.tools.platform_capability_tools import doc_search_tool

        with patch("src.tools.knowledge_tools.search_knowledge_tool", return_value="搜索 '制度' 找到 1 条结果:\n  [公司] 企业微信 AI 助手激活说明书"), \
             patch("src.platform.invoke_capability") as mock_invoke:
            result = doc_search_tool({"query": "制度", "user_id": "u1"})

        self.assertIn("企业微信 AI 助手激活说明书", result)
        mock_invoke.assert_not_called()

    def test_doc_search_tool_handles_wecom_docs_404_gracefully(self) -> None:
        from src.tools.platform_capability_tools import doc_search_tool

        with patch("src.tools.knowledge_tools.search_knowledge_tool", return_value="未找到关于 '指南' 的知识条目"), \
             patch("src.platform.invoke_capability", return_value="[企业微信] HTTP Error 404: Not Found"):
            result = doc_search_tool({"query": "指南", "user_id": "u1"})

        self.assertIn("本地知识库中未找到", result)
        self.assertIn("在线文档搜索接口不可用", result)

    def test_calendar_create_tool_validates_required_fields(self) -> None:
        from src.tools.platform_capability_tools import calendar_create_tool

        self.assertEqual(calendar_create_tool({"summary": "会议"}), "请提供日程标题、开始时间和结束时间")

    def test_calendar_create_tool_delegates_to_platform(self) -> None:
        from src.tools.platform_capability_tools import calendar_create_tool

        with patch("src.platform.invoke_capability", return_value="created") as mock_invoke:
            result = calendar_create_tool(
                {"summary": "周会", "start": "2026-06-22 10:00", "end": "2026-06-22 11:00"}
            )

        self.assertEqual(
            mock_invoke.call_args.args[:4],
            ("calendar.create", "周会", "2026-06-22 10:00", "2026-06-22 11:00"),
        )
        self.assertEqual(result, "created")

    def test_office_service_status_tool_delegates_to_platform(self) -> None:
        from src.tools.platform_capability_tools import office_service_status_tool

        with patch("src.platform.invoke_capability", return_value="ok") as mock_invoke:
            result = office_service_status_tool({})

        self.assertEqual(mock_invoke.call_args.args[:1], ("files.office.service_status",))
        self.assertEqual(result, "ok")

    def test_read_docx_tool_delegates_to_platform(self) -> None:
        from src.tools.platform_capability_tools import read_docx_tool

        with patch("src.platform.invoke_capability_first", return_value="docx-text") as mock_invoke:
            result = read_docx_tool({"path": "/tmp/a.docx"})

        self.assertEqual(mock_invoke.call_args.args[:2], ("files.docx.read", "/tmp/a.docx"))
        self.assertEqual(result, "docx-text")

    def test_enterprise_app_query_tool_delegates_to_platform(self) -> None:
        from src.tools.platform_capability_tools import enterprise_app_query_tool

        with patch("src.platform.enterprise_query_service.execute_enterprise_query", return_value="room-result") as mock_invoke:
            result = enterprise_app_query_tool({"query": "三号会议室有人申请吗", "user_id": "u1", "platform": "wecom"})

        self.assertEqual(mock_invoke.call_args.args[0], "三号会议室有人申请吗")
        self.assertEqual(result, "room-result")

    def test_enterprise_app_query_tool_uses_original_context_when_query_missing(self) -> None:
        from src.tools.platform_capability_tools import enterprise_app_query_tool

        with patch("src.platform.enterprise_query_service.execute_enterprise_query", return_value="审批结果") as mock_invoke:
            result = enterprise_app_query_tool(
                {
                    "_context_text": "查询我所有审批的状态",
                    "user_id": "u1",
                    "_source_provider": "wecom",
                }
            )

        self.assertEqual(result, "审批结果")
        self.assertEqual(mock_invoke.call_args.args[0], "查询我所有审批的状态")

    def test_enterprise_app_action_tool_delegates_to_platform(self) -> None:
        from src.tools.platform_capability_tools import enterprise_app_action_tool

        with patch("src.platform.invoke_capability_first", return_value="created") as mock_invoke:
            result = enterprise_app_action_tool({"action": "meeting.create", "title": "周会", "user_id": "u1"})

        self.assertEqual(mock_invoke.call_args.args[0], "apps.action")
        self.assertEqual(mock_invoke.call_args.args[1], "meeting.create")
        self.assertEqual(result, "created")
