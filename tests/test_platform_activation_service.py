from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


class TestPlatformActivationService(unittest.TestCase):
    def test_activate_platform_bot_saves_env_and_runtime_settings(self) -> None:
        from src.platform.activation_service import activate_platform_bot

        fake_service = MagicMock()
        with patch("src.platform.activation_service.write_env_values") as mock_write_env, \
             patch("src.platform.activation_service.build_settings_service", return_value=fake_service):
            result = activate_platform_bot(
                platform="wecom",
                credentials={
                    "bot_id": "bot-1",
                    "bot_secret": "secret-1",
                    "corp_id": "corp-1",
                    "agent_id": "agent-1",
                    "secret": "app-secret-1",
                },
                activated_by="admin-u1",
                display_name="企业 AI 助手",
                visibility_scope="all",
            )

        self.assertEqual(result.platform, "wecom")
        self.assertTrue(result.managed_by_platform)
        self.assertIn("重启", result.next_action)
        mock_write_env.assert_called_once()
        fake_service.upsert_platform_settings.assert_called_once()

    def test_activate_platform_bot_rejects_missing_required_credentials(self) -> None:
        from src.platform.activation_service import activate_platform_bot

        with self.assertRaises(ValueError) as ctx:
            activate_platform_bot(platform="wecom", credentials={"bot_id": "bot-1"})

        self.assertIn("缺少必填凭据", str(ctx.exception))
        self.assertIn("bot_secret", str(ctx.exception))

    def test_activate_dingtalk_writes_runtime_and_legacy_env_aliases(self) -> None:
        from src.platform.activation_service import activate_platform_bot

        fake_service = MagicMock()
        with patch("src.platform.activation_service.write_env_values") as mock_write_env, \
             patch("src.platform.activation_service.build_settings_service", return_value=fake_service):
            result = activate_platform_bot(
                platform="dingtalk",
                credentials={
                    "client_id": "client-1",
                    "client_secret": "secret-1",
                    "robot_code": "robot-1",
                },
            )

        env_values = mock_write_env.call_args.args[1]
        self.assertEqual(env_values["DINGTALK_CLIENT_ID"], "client-1")
        self.assertEqual(env_values["DINGTALK_APP_KEY"], "client-1")
        self.assertEqual(env_values["DINGTALK_CLIENT_SECRET"], "secret-1")
        self.assertEqual(env_values["DINGTALK_APP_SECRET"], "secret-1")
        self.assertEqual(env_values["DINGTALK_ROBOT_CODE"], "robot-1")
        self.assertIn("robot_code", result.configured_keys)

    def test_list_platform_bot_statuses_reports_metadata(self) -> None:
        from src.config.contracts import PlatformSettingsRecord, PlatformType, PlatformSettingsView
        from src.platform.activation_service import list_platform_bot_statuses

        fake_service = MagicMock()
        fake_service.build_platform_views.return_value = [
            PlatformSettingsView(platform=PlatformType.WECOM, enabled=True, configured_keys=["corp_id"], missing_keys=[]),
        ]
        fake_service.get_platform_settings.side_effect = [
            PlatformSettingsRecord(platform=PlatformType.WECOM, enabled=True, settings={"corp_id": "corp"}, metadata={"managed_by_platform": True, "display_name": "企业 AI 助手", "visibility_scope": "all"}),
            None,
            None,
        ]

        with patch("src.platform.activation_service.build_settings_service", return_value=fake_service):
            statuses = list_platform_bot_statuses()

        self.assertEqual(statuses[0]["platform"], "wecom")
        self.assertEqual(statuses[0]["platform_label"], "企业微信")
        self.assertTrue(statuses[0]["managed_by_platform"])
        self.assertEqual(statuses[0]["display_name"], "企业 AI 助手")
        self.assertIn("restart_required", statuses[0])
        self.assertIn("开通", statuses[1]["next_action"])


if __name__ == "__main__":
    unittest.main()
