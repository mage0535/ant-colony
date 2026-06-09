from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import JsonFileSettingsRepository, SettingsManagementService, export_openvort_env


def main() -> int:
    settings_path = PROJECT_ROOT / "data" / "runtime_settings.json"
    output_path = PROJECT_ROOT / "data" / "openvort_runtime.env"

    repository = JsonFileSettingsRepository(settings_path)
    service = SettingsManagementService(repository)
    snapshot = service.build_runtime_snapshot()
    env_map = export_openvort_env(snapshot)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key}={value}" for key, value in sorted(env_map.items())]
    output_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    print(f"Wrote {len(lines)} entries to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
