#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "== OpenVort server state snapshot =="
echo "Working directory: $(pwd)"

echo
echo "[1] OpenVort source"
if [[ -f "./external/openvort/source/pyproject.toml" ]]; then
  echo "source: present"
else
  echo "source: missing"
fi

echo
echo "[2] Python path probe deps"
if [[ -d "./scratchpad/vendor/openvort_probe" ]]; then
  echo "probe deps: present"
else
  echo "probe deps: missing"
fi

echo
echo "[3] Config files"
if [[ -f "./external/openvort/source/.env" ]]; then
  echo ".env: present"
else
  echo ".env: missing"
fi

echo
echo "[4] Database"
ss -ltn | grep 5432 || true

echo
echo "[5] Web port"
ss -ltn | grep 8090 || true

echo
echo "[6] Docker"
if command -v docker >/dev/null 2>&1; then
  docker --version
  docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
else
  echo "docker: missing"
fi

echo
echo "[7] OpenVort process"
ps -ef | grep openvort | grep -v grep || true

echo
echo "[8] PostgreSQL process"
ps -ef | grep postgres | grep -v grep || true
