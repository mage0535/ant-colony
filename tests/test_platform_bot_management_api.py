from __future__ import annotations

import unittest
from unittest.mock import patch
from fastapi import HTTPException


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
                "restart_required": True,
                "next_action": "企业微信凭据已保存，重启对应 Bot/网关服务后生效。",
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
        self.assertTrue(result["restart_required"])
        self.assertIn("重启", result["next_action"])

    def test_activate_platform_bot_route_returns_400_for_bad_credentials(self) -> None:
        from src.web.dashboard import PlatformBotActivationRequest, activate_platform_bot_api

        with patch("src.platform.activation_service.activate_platform_bot", side_effect=ValueError("缺少必填凭据：bot_secret")):
            with self.assertRaises(HTTPException) as ctx:
                activate_platform_bot_api(
                    "wecom",
                    PlatformBotActivationRequest(credentials={"bot_id": "bot-1"}),
                )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("bot_secret", str(ctx.exception.detail))


if __name__ == "__main__":
    unittest.main()
