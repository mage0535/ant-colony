from __future__ import annotations

import unittest


class TestPlatformAdapterSimulation(unittest.TestCase):
    def test_feishu_contract_simulation_passes_without_credentials(self) -> None:
        from scripts.simulate_platform_adapter_contracts import simulate_feishu_contract

        report = simulate_feishu_contract()

        self.assertTrue(report["ok"])
        self.assertEqual(report["platform"], "feishu")
        self.assertTrue(all(item["ok"] for item in report["scenarios"]))
        scenario_names = {item["name"] for item in report["scenarios"]}
        self.assertIn("group_with_mention_forward_and_reply", scenario_names)
        self.assertIn("file_message_ignored", scenario_names)

    def test_dingtalk_contract_simulation_passes_without_credentials(self) -> None:
        from scripts.simulate_platform_adapter_contracts import simulate_dingtalk_contract

        report = simulate_dingtalk_contract()

        self.assertTrue(report["ok"])
        self.assertEqual(report["platform"], "dingtalk")
        self.assertTrue(all(item["ok"] for item in report["scenarios"]))
        scenario_names = {item["name"] for item in report["scenarios"]}
        self.assertIn("group_with_mention_forward_and_reply", scenario_names)
        self.assertIn("file_message_ignored", scenario_names)

    def test_combined_report_passes(self) -> None:
        from scripts.simulate_platform_adapter_contracts import build_report

        report = build_report()

        self.assertTrue(report["ok"])
        self.assertEqual(report["mode"], "local-simulation")
        self.assertEqual({item["platform"] for item in report["platforms"]}, {"feishu", "dingtalk"})


if __name__ == "__main__":
    unittest.main()
