from __future__ import annotations

import os
from pathlib import Path


def restrict_to_owner(path: str | Path) -> None:
    os.chmod(str(path), 0o600)
