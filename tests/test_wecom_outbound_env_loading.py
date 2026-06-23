from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestWeComOutboundEnvLoading(unittest.TestCase):
    def test_load_env_values_reads_secret_from_env_file(self) -> None:
        import importlib
        import src.gateway.wecom_outbound as outbound

        with tempfile.TemporaryDirectory() as td:
            env_dir = Path(td) / "infra"
            env_dir.mkdir()
            env_path = env_dir / ".env.wecom"
            env_path.write_text(
                "WECOM_CORP_ID=corp-1\nWECOM_SECRET=secret-1\nWECOM_AGENT_ID=1000001\n",
                encoding="utf-8",
            )
            with patch("src.gateway.wecom_outbound.os.getcwd", return_value=td):
                importlib.reload(outbound)

                self.assertEqual(outbound.CORP_ID, "corp-1")
                self.assertEqual(outbound.APP_SECRET, "secret-1")
                self.assertEqual(outbound.AGENT_ID, 1000001)
