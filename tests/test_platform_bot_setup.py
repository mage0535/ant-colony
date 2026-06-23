from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class TestPlatformBotSetup(unittest.TestCase):
    def test_platform_env_names_are_distinct_for_dual_wecom_mode(self) -> None:
        from src.platform.bot_setup import PLATFORM_SPECS

        self.assertEqual(
            PLATFORM_SPECS["wecom"]["env_keys"],
            ("WECOM_BOT_ID", "WECOM_BOT_SECRET"),
        )
        self.assertEqual(
            PLATFORM_SPECS["wecom_callback"]["env_keys"],
            ("WECOM_CORP_ID", "WECOM_SECRET"),
        )

    def test_normalize_wecom_result_extracts_bot_credentials(self) -> None:
        from src.platform.bot_setup import normalize_registration_result

        result = normalize_registration_result(
            "wecom",
            {"bot_id": "bot-123", "secret": "sec-456"},
        )

        self.assertEqual(
            result,
            {"WECOM_BOT_ID": "bot-123", "WECOM_BOT_SECRET": "sec-456"},
        )

    def test_normalize_feishu_result_extracts_app_credentials(self) -> None:
        from src.platform.bot_setup import normalize_registration_result

        result = normalize_registration_result(
            "feishu",
            {"app_id": "cli_a", "app_secret": "sec_b", "domain": "lark"},
        )

        self.assertEqual(result["FEISHU_APP_ID"], "cli_a")
        self.assertEqual(result["FEISHU_APP_SECRET"], "sec_b")
        self.assertEqual(result["FEISHU_DOMAIN"], "lark")

    def test_normalize_dingtalk_result_extracts_client_credentials(self) -> None:
        from src.platform.bot_setup import normalize_registration_result

        result = normalize_registration_result(
            "dingtalk",
            {"client_id": "ding_a", "client_secret": "ding_b"},
        )

        self.assertEqual(
            result,
            {"DINGTALK_CLIENT_ID": "ding_a", "DINGTALK_CLIENT_SECRET": "ding_b"},
        )

    def test_write_env_values_merges_without_dropping_existing_lines(self) -> None:
        from src.platform.bot_setup import write_env_values

        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env.wecom"
            env_path.write_text(
                "WECOM_CORP_ID=corp-1\nEXISTING_KEEP=yes\n",
                encoding="utf-8",
            )

            write_env_values(
                env_path,
                {"WECOM_BOT_ID": "bot-1", "WECOM_BOT_SECRET": "secret-1"},
            )

            content = env_path.read_text(encoding="utf-8")
            self.assertIn("WECOM_CORP_ID=corp-1", content)
            self.assertIn("EXISTING_KEEP=yes", content)
            self.assertIn("WECOM_BOT_ID=bot-1", content)
            self.assertIn("WECOM_BOT_SECRET=secret-1", content)

    def test_render_qr_to_terminal_returns_true_when_qrcode_available(self) -> None:
        from src.platform.bot_setup import render_qr_to_terminal

        try:
            import qrcode  # noqa: F401
        except ImportError:
            self.skipTest("qrcode not installed in local environment")

        self.assertTrue(render_qr_to_terminal("https://example.com/qr"))
