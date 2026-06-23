from __future__ import annotations

import unittest
from unittest.mock import patch


class TestEmailCapabilityTools(unittest.TestCase):
    def test_send_email_tool_delegates_to_email_tool(self) -> None:
        from src.tools.email_capability_tools import send_email_tool

        with patch("src.platform.invoke_capability_first", return_value="ok") as mock_send:
            result = send_email_tool({"to": "a@test.local", "subject": "s", "body": "b", "cc": "c@test.local"})

        self.assertEqual(mock_send.call_args.args[:5], ("mail.send", "a@test.local", "s", "b", "c@test.local"))
        self.assertEqual(result, "ok")

    def test_list_emails_tool_delegates_to_email_tool(self) -> None:
        from src.tools.email_capability_tools import list_emails_tool

        with patch("src.platform.invoke_capability", return_value="emails") as mock_list:
            result = list_emails_tool({"limit": 5})

        self.assertEqual(mock_list.call_args.args[:2], ("mail.list", 5))
        self.assertEqual(result, "emails")

    def test_search_emails_tool_delegates_to_email_tool(self) -> None:
        from src.tools.email_capability_tools import search_emails_tool

        with patch("src.platform.invoke_capability", return_value="matches") as mock_search:
            result = search_emails_tool({"query": "invoice"})

        self.assertEqual(mock_search.call_args.args[:2], ("mail.search", "invoice"))
        self.assertEqual(result, "matches")

    def test_get_email_tool_delegates_to_email_tool(self) -> None:
        from src.tools.email_capability_tools import get_email_tool

        with patch("src.platform.invoke_capability_first", return_value="body") as mock_get:
            result = get_email_tool({"uid": "42"})

        self.assertEqual(mock_get.call_args.args[:2], ("mail.get", "42"))
        self.assertEqual(result, "body")
