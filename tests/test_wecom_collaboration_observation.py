from __future__ import annotations

import unittest


class TestWeComCollaborationObservation(unittest.TestCase):
    def test_build_collaboration_report_passes(self) -> None:
        from scripts.validate_wecom_collaboration_observation import build_collaboration_report

        report = build_collaboration_report()

        self.assertTrue(report["ok"])
        self.assertEqual(report["linked_spaces"], ["dept-space-2"])
        self.assertGreaterEqual(report["fanout_count"], 1)
        self.assertIn("u-leader", report["fanout_targets"])


if __name__ == "__main__":
    unittest.main()
