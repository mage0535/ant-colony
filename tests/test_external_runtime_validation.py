from __future__ import annotations

import unittest
from unittest.mock import patch


class TestExternalRuntimeValidation(unittest.TestCase):
    def test_collect_runtime_validation_report_marks_missing_platform_env(self) -> None:
        from scripts.validate_external_runtime import collect_runtime_validation_report

        with patch.dict("os.environ", {}, clear=True), patch("pathlib.Path.exists", return_value=False):
            report = collect_runtime_validation_report()

        self.assertIn("platforms", report)
        self.assertFalse(report["platforms"]["wecom"]["configured"])
        self.assertFalse(report["platforms"]["feishu"]["configured"])
        self.assertFalse(report["platforms"]["dingtalk"]["configured"])

    def test_collect_runtime_validation_report_reads_env_file_keys(self) -> None:
        from scripts.validate_external_runtime import collect_runtime_validation_report

        fake_env = "WECOM_BOT_ID=bot-x\nWECOM_BOT_SECRET=secret-x\n"
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.read_text", return_value=fake_env),
        ):
            report = collect_runtime_validation_report()

        self.assertTrue(report["platforms"]["wecom"]["configured"])
        self.assertEqual(report["platforms"]["wecom"]["source"], "env_file")
