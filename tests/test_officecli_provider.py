from __future__ import annotations

import unittest
from unittest.mock import patch


class TestOfficeCliProvider(unittest.TestCase):
    def test_is_configured_checks_binary(self) -> None:
        from src.platform.officecli_provider import OfficeCliProvider

        with patch("os.path.isfile", return_value=True):
            self.assertTrue(OfficeCliProvider().is_configured())

        with patch("os.path.isfile", return_value=False):
            self.assertFalse(OfficeCliProvider().is_configured())

    def test_healthcheck_returns_version_output(self) -> None:
        from src.platform.officecli_provider import OfficeCliProvider

        class Completed:
            stdout = "officecli 1.0.0"
            stderr = ""
            returncode = 0

        with patch("os.path.isfile", return_value=True), \
             patch("subprocess.run", return_value=Completed()):
            result = OfficeCliProvider().healthcheck()

        self.assertEqual(result, "officecli 1.0.0")
