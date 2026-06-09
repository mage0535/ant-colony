#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

VENDOR_DIR="./scratchpad/vendor/openvort_probe"
SOURCE_DIR="./external/openvort/source/src"

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "FAIL: neither python3 nor python is available."
  exit 1
fi

echo "== P-1 OpenVort validation (Linux) =="
echo "Workspace root: ./"
echo "Source dir: ./external/openvort/source/src"
echo "Vendor deps dir: ./scratchpad/vendor/openvort_probe"

if [[ ! -d "$SOURCE_DIR" ]]; then
  echo "FAIL: OpenVort source is missing. Acquire source first."
  exit 1
fi

if [[ ! -d "$VENDOR_DIR" ]]; then
  echo "FAIL: vendor probe dependencies are missing."
  echo "Next step: run ./scripts/install_openvort_probe_deps.sh"
  exit 1
fi

export PYTHONPATH="$(cd "$VENDOR_DIR" && pwd):$(cd "$SOURCE_DIR" && pwd)"
export PYTHONIOENCODING="utf-8"
export PYTHONUTF8="1"

"$PYTHON_BIN" ./scratchpad/p1_verify_openvort.py
