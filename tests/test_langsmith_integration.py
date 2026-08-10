from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


class TestLangSmithIntegration(unittest.TestCase):
    def test_validate_langsmith_cloud_reports_missing_key(self) -> None:
        from scripts.validate_langsmith_cloud import validate_langsmith_cloud

        with patch.dict("os.environ", {}, clear=True), patch("src.observability.langsmith_support._load_env_file", return_value={}):
            result = validate_langsmith_cloud()

        self.assertFalse(result["configured"])

    def test_get_langsmith_client_does_not_require_tracing_enabled(self) -> None:
        from src.observability.langsmith_support import get_langsmith_client, langsmith_enabled

        with (
            patch.dict("os.environ", {"LANGSMITH_API_KEY": "test-key", "LANGSMITH_TRACING": "false"}, clear=True),
            patch("src.observability.langsmith_support._load_env_file", return_value={}),
            patch("langsmith.Client", return_value="client") as client_cls,
        ):
            self.assertFalse(langsmith_enabled())
            self.assertEqual(get_langsmith_client(), "client")

        client_cls.assert_called_once()

    def test_langsmith_tracing_defaults_to_disabled_even_with_key(self) -> None:
        from src.observability.langsmith_support import configure_langsmith_env, langsmith_enabled

        with (
            patch.dict("os.environ", {"LANGSMITH_API_KEY": "test-key"}, clear=True),
            patch("src.observability.langsmith_support._load_env_file", return_value={}),
        ):
            configure_langsmith_env()

            self.assertEqual("false", __import__("os").environ["LANGSMITH_TRACING"])
            self.assertFalse(langsmith_enabled())

    def test_langsmith_tracing_requires_publish_opt_in(self) -> None:
        from src.observability.langsmith_support import langsmith_enabled

        with (
            patch.dict("os.environ", {"LANGSMITH_API_KEY": "test-key", "LANGSMITH_TRACING": "true"}, clear=True),
            patch("src.observability.langsmith_support._load_env_file", return_value={}),
        ):
            self.assertFalse(langsmith_enabled())

    def test_langsmith_tracing_can_be_explicitly_published(self) -> None:
        from src.observability.langsmith_support import langsmith_enabled

        with (
            patch.dict(
                "os.environ",
                {"LANGSMITH_API_KEY": "test-key", "LANGSMITH_TRACING": "true", "LANGSMITH_PUBLISH": "true"},
                clear=True,
            ),
            patch("src.observability.langsmith_support._load_env_file", return_value={}),
        ):
            self.assertTrue(langsmith_enabled())

    def test_langsmith_publish_false_overrides_tracing(self) -> None:
        from src.observability.langsmith_support import configure_langsmith_env, langsmith_enabled

        with (
            patch.dict(
                "os.environ",
                {"LANGSMITH_API_KEY": "test-key", "LANGSMITH_TRACING": "true", "LANGSMITH_PUBLISH": "false"},
                clear=True,
            ),
            patch("src.observability.langsmith_support._load_env_file", return_value={}),
        ):
            configure_langsmith_env()

            self.assertEqual("false", __import__("os").environ["LANGSMITH_TRACING"])
            self.assertEqual("false", __import__("os").environ["LANGCHAIN_TRACING_V2"])
            self.assertFalse(langsmith_enabled())

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
