from __future__ import annotations
import asyncio
import unittest
from unittest.mock import patch


class TestPlatformLiveValidation(unittest.TestCase):
    def test_validate_feishu_configuration_reports_missing_values(self) -> None:
        from scripts.validate_feishu_live import validate_feishu_configuration

        report = asyncio.run(validate_feishu_configuration({}))
        self.assertFalse(report["api"]["configured"])

    def test_validate_dingtalk_configuration_reports_missing_values(self) -> None:
        from scripts.validate_dingtalk_live import validate_dingtalk_configuration

        report = asyncio.run(validate_dingtalk_configuration({}))
        self.assertFalse(report["api"]["configured"])

    def test_validate_feishu_configuration_reports_success_with_mocked_api(self) -> None:
        from scripts.validate_feishu_live import validate_feishu_configuration

        async def run():
            with patch("scripts.validate_feishu_live.fetch_feishu_token", return_value={"ok": True, "token_prefix": "abc***"}):
                return await validate_feishu_configuration({"FEISHU_APP_ID": "app", "FEISHU_APP_SECRET": "secret"})

        report = asyncio.run(run())
        self.assertTrue(report["api"]["ok"])

    def test_validate_dingtalk_configuration_reports_success_with_mocked_api(self) -> None:
        from scripts.validate_dingtalk_live import validate_dingtalk_configuration

        async def run():
            with patch("scripts.validate_dingtalk_live.fetch_dingtalk_token", return_value={"ok": True, "token_prefix": "abc***"}):
                return await validate_dingtalk_configuration({"DINGTALK_CLIENT_ID": "id", "DINGTALK_CLIENT_SECRET": "secret"})

        report = asyncio.run(run())
        self.assertTrue(report["api"]["ok"])
