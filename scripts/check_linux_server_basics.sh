#!/usr/bin/env bash
set -euo pipefail

echo "== Linux server basics check =="

check_cmd() {
  local label="$1"
  local cmd="$2"

  if command -v "$cmd" >/dev/null 2>&1; then
    local path
    path="$(command -v "$cmd")"
    echo "$label: true ($path)"
  else
    echo "$label: false"
  fi
}

check_cmd "python3 available" "python3"
check_cmd "pip available" "pip"
check_cmd "git available" "git"
check_cmd "docker available" "docker"
check_cmd "node available" "node"
check_cmd "npm available" "npm"

echo
echo "Recommended next steps:"
if ! command -v python3 >/dev/null 2>&1; then
  echo "- Install Python 3.11+."
fi
if ! command -v pip >/dev/null 2>&1; then
  echo "- Install pip for the target Python runtime."
fi
if ! command -v git >/dev/null 2>&1; then
  echo "- Install git so the source checkout can be updated or verified."
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "- Install Docker if you plan to use OpenVort's auto-start PostgreSQL path."
fi
if ! command -v node >/dev/null 2>&1; then
  echo "- Install Node.js 20+ if frontend build or dev workflow will run on the server."
fi
if ! command -v npm >/dev/null 2>&1; then
  echo "- Install npm together with Node.js."
fi
