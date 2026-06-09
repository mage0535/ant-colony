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

VENDOR_DIR="./scratchpad/vendor/openvort_probe"
SOURCE_DIR="./external/openvort/source/src"
LOG_FILE="./scratchpad/openvort_http_probe.log"

if [[ ! -d "$VENDOR_DIR" ]]; then
  echo "FAIL: probe dependency directory is missing."
  exit 1
fi

if [[ ! -d "$SOURCE_DIR" ]]; then
  echo "FAIL: OpenVort source directory is missing."
  exit 1
fi

export PYTHONPATH="$(cd "$VENDOR_DIR" && pwd):$(cd "$SOURCE_DIR" && pwd)"
export PYTHONIOENCODING="utf-8"
export PYTHONUTF8="1"

echo "== OpenVort HTTP probe =="
echo "Working directory: $(pwd)"
echo "Log file: $LOG_FILE"

rm -f "$LOG_FILE"

cleanup() {
  if [[ -n "${OPENVORT_PID:-}" ]]; then
    kill "$OPENVORT_PID" >/dev/null 2>&1 || true
    wait "$OPENVORT_PID" >/dev/null 2>&1 || true
  fi
}

trap cleanup EXIT

timeout 60s "$PYTHON_BIN" -m openvort start --dev >"$LOG_FILE" 2>&1 &
OPENVORT_PID=$!

for _ in $(seq 1 20); do
  if curl -s http://127.0.0.1:8090/ >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo
echo "[1] Port check"
ss -ltn | grep 8090 || true

echo
echo "[2] HTTP GET /"
curl -s http://127.0.0.1:8090/ | sed -n '1,20p'

echo
echo "[3] HTTP HEAD /"
curl -I -s http://127.0.0.1:8090/ | sed -n '1,10p'

echo
echo "[4] Log tail"
tail -n 40 "$LOG_FILE" || true
