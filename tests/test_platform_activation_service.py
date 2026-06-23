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
        mock_write_env.assert_called_once()
        fake_service.upsert_platform_settings.assert_called_once()

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
        self.assertTrue(statuses[0]["managed_by_platform"])
        self.assertEqual(statuses[0]["display_name"], "企业 AI 助手")


if __name__ == "__main__":
    unittest.main()
