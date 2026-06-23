from __future__ import annotations
import unittest
from unittest.mock import patch


class TestBasicToolModules(unittest.TestCase):
    def test_contact_search_tool_uses_invoke_capability(self) -> None:
        from src.tools.basic_tool_modules import contact_search_tool

        with patch("src.platform.invoke_capability", return_value="contact-result") as mock_invoke:
            result = contact_search_tool({"query": "马戈", "user_id": "u1", "_source_provider": "wecom_bot"})

        self.assertEqual(mock_invoke.call_args.args[:2], ("contacts.search", "马戈"))
        self.assertEqual(mock_invoke.call_args.kwargs["context"]["user_id"], "u1")
        self.assertEqual(result, "contact-result")

    def test_calendar_agenda_tool_uses_invoke_capability(self) -> None:
        from src.tools.basic_tool_modules import calendar_agenda_tool

        with patch("src.platform.invoke_capability", return_value="agenda-result") as mock_invoke:
            result = calendar_agenda_tool({"days": 3, "_source_transport": "wecom_bot_ws"})

        self.assertEqual(mock_invoke.call_args.args[:2], ("calendar.list", 3))
        self.assertEqual(mock_invoke.call_args.kwargs["context"]["transport"], "wecom_bot_ws")
        self.assertEqual(result, "agenda-result")

    def test_now_tool_returns_timestamp_string(self) -> None:
        from src.tools.basic_tool_modules import now_tool

        result = now_tool({})

        self.assertRegex(result, r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")
