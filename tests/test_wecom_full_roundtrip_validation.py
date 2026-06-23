from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch


class TestWeComFullRoundtripValidation(unittest.TestCase):
    def test_validate_full_roundtrip_reports_push_success(self) -> None:
        from scripts.validate_wecom_full_roundtrip import validate_full_roundtrip

        fake_response = type("Resp", (), {"text": '[BOT_FILE]{"path":"/tmp/a.docx","filename":"a.docx","download_url":"http://x"}'})()
        fake_result = type("Result", (), {"response": fake_response})()
        fake_ack = type("Ack", (), {"response": type("Resp", (), {"text": "已收到文件"})()})()
        with (
            patch("scripts.validate_wecom_full_roundtrip.pick_probe_user", return_value="u1"),
            patch("scripts.validate_wecom_full_roundtrip.upload_file", return_value="media-1"),
            patch.object(Path, "is_file", return_value=True),
            patch("scripts.validate_wecom_full_roundtrip.InboundGatewayService.handle_wecom_payload", side_effect=[fake_ack, fake_result]),
            patch("scripts.validate_wecom_full_roundtrip.send_file_card", return_value=True),
            patch("scripts.validate_wecom_full_roundtrip.send_file", return_value=True),
        ):
            report = validate_full_roundtrip()

        self.assertTrue(report["uploaded"])
        self.assertTrue(report["bot_file"])
        self.assertTrue(report["pushed"])
