#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "FAIL: neither python3 nor python is available."
  exit 1
fi

RUNTIME_SETTINGS="./data/runtime_settings.json"
EXPORTED_ENV="./data/openvort_runtime.env"
TARGET_ENV="./external/openvort/source/.env"
BACKUP_ENV="./external/openvort/source/.env.backup.runtime"

echo "== Apply runtime settings to OpenVort .env =="
echo "Runtime settings: $RUNTIME_SETTINGS"
echo "Exported env: $EXPORTED_ENV"
echo "Target env: $TARGET_ENV"

if [[ ! -f "$RUNTIME_SETTINGS" ]]; then
  echo "FAIL: runtime settings file is missing."
  exit 1
fi

if [[ ! -f "$TARGET_ENV" ]]; then
  echo "FAIL: target OpenVort .env is missing."
  exit 1
fi

"$PYTHON_BIN" ./scripts/export_runtime_settings_to_openvort_env.py

cp "$TARGET_ENV" "$BACKUP_ENV"
echo "Backed up current .env to $BACKUP_ENV"

python3 - "$TARGET_ENV" "$EXPORTED_ENV" <<'PY'
from pathlib import Path
import sys

target_path = Path(sys.argv[1])
exported_path = Path(sys.argv[2])

target_lines = target_path.read_text(encoding="utf-8").splitlines()
exported_map = {}
for line in exported_path.read_text(encoding="utf-8").splitlines():
    if not line.strip() or line.strip().startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    exported_map[key] = value

written = set()
new_lines = []
for line in target_lines:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in line:
        new_lines.append(line)
        continue
    key, _value = line.split("=", 1)
    if key in exported_map:
        new_lines.append(f"{key}={exported_map[key]}")
        written.add(key)
    else:
        new_lines.append(line)

for key, value in exported_map.items():
    if key not in written:
        new_lines.append(f"{key}={value}")

target_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
PY

echo "Applied exported runtime settings into $TARGET_ENV"
echo "Next steps:"
echo "- Inspect $EXPORTED_ENV"
echo "- Re-run ./scripts/check_openvort_prereqs.sh"
echo "- Re-run ./scripts/run_p1_openvort.sh"
