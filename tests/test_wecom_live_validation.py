from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch


class TestWeComLiveValidation(unittest.TestCase):
    def test_load_env_file_returns_keys_without_values(self) -> None:
        from scripts.validate_wecom_live import load_env_file

        with patch("pathlib.Path.exists", return_value=True), patch(
            "pathlib.Path.read_text",
            return_value="WECOM_BOT_ID=bot\nWECOM_BOT_SECRET=secret\n",
        ):
            values = load_env_file("infra/.env.wecom")

        self.assertEqual(values["WECOM_BOT_ID"], "bot")
        self.assertEqual(values["WECOM_BOT_SECRET"], "secret")

    def test_validate_wecom_configuration_reports_missing_values(self) -> None:
        from scripts.validate_wecom_live import validate_wecom_configuration

        report = asyncio.run(validate_wecom_configuration({}))

        self.assertFalse(report["corp_api"]["configured"])
        self.assertFalse(report["bot_ws"]["configured"])

    def test_validate_wecom_configuration_reports_success_with_mocked_clients(self) -> None:
        from scripts.validate_wecom_live import validate_wecom_configuration

        async def run() -> dict:
            with (
                patch("scripts.validate_wecom_live.fetch_wecom_access_token", return_value={"ok": True, "token_prefix": "abc***"}),
                patch("scripts.validate_wecom_live.validate_wecom_bot_websocket", new=AsyncMock(return_value={"ok": True, "ws_url": "wss://example"})),
            ):
                return await validate_wecom_configuration(
                    {
                        "WECOM_CORP_ID": "corp",
                        "WECOM_SECRET": "secret",
                        "WECOM_BOT_ID": "bot",
                        "WECOM_BOT_SECRET": "bot-secret",
                    }
                )

        report = asyncio.run(run())
        self.assertTrue(report["corp_api"]["ok"])
        self.assertTrue(report["bot_ws"]["ok"])
