from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SCENARIOS = [
    "tests/test_file_message_pairing.py",
    "tests/test_wecom_bot_bridge.py",
    "tests/test_document_pipeline.py",
    "tests/test_platform_adapter_startup.py",
    "tests/test_feishu_adapter.py",
    "tests/test_dingtalk_adapter.py",
    "tests/test_platform_adapter_simulation.py",
]


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    command = [sys.executable, "-m", "pytest", "-q", *SCENARIOS]
    completed = subprocess.run(command, cwd=root)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
