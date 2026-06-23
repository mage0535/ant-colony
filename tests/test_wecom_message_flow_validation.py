from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestWeComMessageFlowValidation(unittest.TestCase):
    def test_pick_probe_user_prefers_explicit_env_value(self) -> None:
        from scripts.validate_wecom_message_flow import pick_probe_user

        with patch.dict("os.environ", {"WECOM_PROBE_USER_ID": "u-explicit"}, clear=True):
            user_id = pick_probe_user()

        self.assertEqual(user_id, "u-explicit")

    def test_pick_probe_user_falls_back_to_leader(self) -> None:
        from scripts.validate_wecom_message_flow import pick_probe_user

        class FakeClient:
            def get_admin_userids(self):
                return set()

            def get_department_leader_ids(self):
                return {"u-leader"}

        with patch.dict("os.environ", {}, clear=True), patch("scripts.validate_wecom_message_flow.WeComClient", return_value=FakeClient()):
            user_id = pick_probe_user()

        self.assertEqual(user_id, "u-leader")

    def test_validate_outbound_flow_runs_three_checks(self) -> None:
        from scripts.validate_wecom_message_flow import validate_outbound_flow

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "probe.txt"
            with (
                patch("scripts.validate_wecom_message_flow.pick_probe_user", return_value="u1"),
                patch("scripts.validate_wecom_message_flow.send_text", return_value=True),
                patch("scripts.validate_wecom_message_flow.send_file_card", return_value=True),
                patch("scripts.validate_wecom_message_flow.send_file", return_value=True),
            ):
                report = validate_outbound_flow(str(path))

        self.assertTrue(report["text"]["ok"])
        self.assertTrue(report["file_card"]["ok"])
        self.assertTrue(report["file_send"]["ok"])
