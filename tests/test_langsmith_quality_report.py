from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch


class _Run:
    def __init__(self, *, name: str, run_type: str, duration_seconds: float, error=None, outputs=None) -> None:
        self.name = name
        self.run_type = run_type
        self.start_time = datetime.now(timezone.utc)
        self.end_time = self.start_time + timedelta(seconds=duration_seconds)
        self.error = error
        self.outputs = outputs


class TestLangSmithQualityReport(unittest.TestCase):
    def test_collect_quality_report_summarizes_slow_failed_and_low_quality_runs(self) -> None:
        from scripts.langsmith_quality_report import collect_quality_report

        fake_client = type(
            "Client",
            (),
            {
                "list_runs": lambda self, project_name, limit: [
                    _Run(name="generate_document", run_type="tool", duration_seconds=12.0, outputs={"text": "抱歉，未找到模板内容"}),
                    _Run(name="handle_wecom_payload", run_type="chain", duration_seconds=1.2, error="HTTP 500"),
                    _Run(name="build_memory_context", run_type="retriever", duration_seconds=2.0, outputs={"text": "ok"}),
                ]
            },
        )()

        with patch("scripts.langsmith_quality_report.get_langsmith_client", return_value=fake_client), \
             patch("scripts.langsmith_quality_report.configure_langsmith_env"), \
             patch("scripts.langsmith_quality_report.os.environ", {"LANGSMITH_PROJECT": "ant-colony"}):
            report = collect_quality_report(limit=10, slow_threshold_seconds=8.0)

        self.assertTrue(report["configured"])
        self.assertEqual(report["project"], "ant-colony")
        self.assertEqual(report["run_count"], 3)
        self.assertEqual(report["slow_runs"][0]["name"], "generate_document")
        self.assertEqual(report["failed_runs"][0]["name"], "handle_wecom_payload")
        self.assertEqual(report["low_quality_document_runs"][0]["name"], "generate_document")


if __name__ == "__main__":
    unittest.main()
