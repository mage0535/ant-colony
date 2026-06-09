#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYPROJECT="./external/openvort/source/pyproject.toml"
TARGET_DIR="./scratchpad/vendor/openvort_probe"

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "FAIL: neither python3 nor python is available."
  exit 1
fi

echo "== Install OpenVort probe dependencies (Linux) =="
echo "Pyproject: ./external/openvort/source/pyproject.toml"
echo "Target dir: ./scratchpad/vendor/openvort_probe"

if [[ ! -f "$PYPROJECT" ]]; then
  echo "FAIL: OpenVort pyproject.toml is missing. Run ./scripts/acquire_openvort.ps1 -Clone first."
  exit 1
fi

rm -rf "$TARGET_DIR"
mkdir -p "$TARGET_DIR"

"$PYTHON_BIN" - "$PYPROJECT" "$TARGET_DIR" <<'PY'
from pathlib import Path
import subprocess
import sys
import tomllib

pyproject = Path(sys.argv[1])
target_dir = Path(sys.argv[2])
data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
dependencies = data["project"]["dependencies"]

cmd = [sys.executable, "-m", "pip", "install", "--target", str(target_dir), *dependencies]
print("Running:", " ".join(cmd))
subprocess.check_call(cmd)
PY

echo "Installed probe dependencies into ./scratchpad/vendor/openvort_probe"
echo "Next steps:"
echo "- Run ./scripts/check_openvort_prereqs.sh"
echo "- Run ./scripts/run_p1_openvort.sh"
