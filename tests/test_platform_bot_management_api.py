from __future__ import annotations

import unittest
from unittest.mock import patch


class TestPlatformBotManagementApi(unittest.TestCase):
    def test_list_platform_bots_route(self) -> None:
        from src.web.dashboard import list_platform_bots

        with patch("src.platform.activation_service.list_platform_bot_statuses", return_value=[{"platform": "wecom", "enabled": True}]):
            result = list_platform_bots()

        self.assertEqual(result["platforms"][0]["platform"], "wecom")

    def test_activate_platform_bot_route(self) -> None:
        from src.web.dashboard import PlatformBotActivationRequest, activate_platform_bot_api

        fake_result = type(
            "ActivationResult",
            (),
            {
                "platform": "wecom",
                "enabled": True,
                "managed_by_platform": True,
                "configured_keys": ["corp_id", "agent_id"],
                "visibility_scope": "all",
                "display_name": "企业 AI 助手",
                "auto_permissions": ["docs.full"],
            },
        )()

        with patch("src.platform.activation_service.activate_platform_bot", return_value=fake_result):
            result = activate_platform_bot_api(
                "wecom",
                PlatformBotActivationRequest(
                    credentials={"corp_id": "corp-1"},
                    activated_by="admin-u1",
                    display_name="企业 AI 助手",
                    visibility_scope="all",
                    auto_permissions=["docs.full"],
                ),
            )

        self.assertTrue(result["enabled"])
        self.assertEqual(result["display_name"], "企业 AI 助手")


if __name__ == "__main__":
    unittest.main()
