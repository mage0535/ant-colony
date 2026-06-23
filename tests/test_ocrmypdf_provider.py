from __future__ import annotations

import unittest
from unittest.mock import patch


class TestOcrmypdfProvider(unittest.TestCase):
    def test_is_configured_checks_binary(self) -> None:
        from src.platform.ocrmypdf_provider import OcrmypdfProvider

        with patch("shutil.which", return_value="/usr/bin/ocrmypdf"):
            self.assertTrue(OcrmypdfProvider().is_configured())

        with patch("shutil.which", return_value=None):
            self.assertFalse(OcrmypdfProvider().is_configured())

    def test_healthcheck_returns_version_when_available(self) -> None:
        from src.platform.ocrmypdf_provider import OcrmypdfProvider

        class Completed:
            stdout = "ocrmypdf 16.0.0"
            stderr = ""
            returncode = 0

        with patch("shutil.which", return_value="/usr/bin/ocrmypdf"), \
             patch("subprocess.run", return_value=Completed()):
            result = OcrmypdfProvider().healthcheck()

        self.assertIn("ocrmypdf 16.0.0", result)

    def test_ocr_pdf_document_builds_command(self) -> None:
        from src.platform.ocrmypdf_provider import OcrmypdfProvider

        class Completed:
            stdout = "done"
            stderr = ""
            returncode = 0

        with patch("shutil.which", return_value="/usr/bin/ocrmypdf"), \
             patch("subprocess.run", return_value=Completed()) as mock_run:
            result = OcrmypdfProvider().ocr_pdf_document("a.pdf", "out.pdf", "chi_sim+eng")

        cmd = mock_run.call_args.args[0]
        self.assertIn("ocrmypdf", cmd[0])
        self.assertIn("-l", cmd)
        self.assertIn("chi_sim+eng", cmd)
        self.assertEqual(result, "OCR completed: out.pdf")
