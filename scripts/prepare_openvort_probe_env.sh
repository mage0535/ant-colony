#!/usr/bin/env bash
set -euo pipefail

FORCE=false
if [[ "${1:-}" == "--force" ]]; then
  FORCE=true
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

SOURCE_SAMPLE="./scratchpad/openvort_probe.env.sample"
TARGET_ENV="./external/openvort/source/.env"
BACKUP_ENV="./external/openvort/source/.env.backup"

echo "== Prepare OpenVort probe .env (Linux) =="
echo "Source sample: ./scratchpad/openvort_probe.env.sample"
echo "Target file: ./external/openvort/source/.env"

if [[ ! -f "$SOURCE_SAMPLE" ]]; then
  echo "FAIL: source sample is missing."
  exit 1
fi

if [[ ! -d "./external/openvort/source" ]]; then
  echo "FAIL: OpenVort source checkout is missing. Run ./scripts/acquire_openvort.ps1 -Clone first."
  exit 1
fi

if [[ -f "$TARGET_ENV" && "$FORCE" != "true" ]]; then
  echo "SKIP: target .env already exists."
  echo "Use --force to overwrite it intentionally."
  exit 0
fi

if [[ -f "$TARGET_ENV" ]]; then
  cp "$TARGET_ENV" "$BACKUP_ENV"
  echo "Backed up existing .env to ./external/openvort/source/.env.backup"
fi

cp "$SOURCE_SAMPLE" "$TARGET_ENV"
echo "Prepared ./external/openvort/source/.env"
echo
echo "Next steps:"
echo "- Fill in real PostgreSQL / LLM / admin / WeCom values."
echo "- Run ./scripts/check_openvort_prereqs.sh"
echo "- Run ./scripts/run_p1_openvort.sh"
