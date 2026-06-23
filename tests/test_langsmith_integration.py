from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


class TestLangSmithIntegration(unittest.TestCase):
    def test_validate_langsmith_cloud_reports_missing_key(self) -> None:
        from scripts.validate_langsmith_cloud import validate_langsmith_cloud

        with patch.dict("os.environ", {}, clear=True), patch("src.observability.langsmith_support._load_env_file", return_value={}):
            result = validate_langsmith_cloud()

        self.assertFalse(result["configured"])

    def test_collect_run_report_uses_client(self) -> None:
        from scripts.langsmith_run_report import collect_run_report

        fake_run = type("Run", (), {"run_type": "chain", "name": "generate_document"})()
        fake_client = MagicMock()
        fake_client.list_runs.return_value = [fake_run]
        with (
            patch("scripts.langsmith_run_report.get_langsmith_client", return_value=fake_client),
            patch("scripts.langsmith_run_report.configure_langsmith_env"),
            patch.dict("os.environ", {"LANGSMITH_PROJECT": "ant-colony"}, clear=False),
        ):
            result = collect_run_report(limit=10)

        self.assertTrue(result["configured"])
        self.assertEqual(result["run_count"], 1)
        self.assertEqual(result["run_types"]["chain"], 1)
