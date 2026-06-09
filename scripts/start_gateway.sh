#!/usr/bin/env bash
# Start the ant-colony gateway webhook server.
# OpenVort should forward WeCom messages to http://<host>:<port>/
# Usage: GATEWAY_PROFILE=server-deepseek ./scripts/start_gateway.sh
set -euo pipefail

cd "$(dirname "$0")/.."

PORT="${GATEWAY_PORT:-18090}"
HOST="${GATEWAY_HOST:-0.0.0.0}"
PROFILE="${GATEWAY_PROFILE:-server-deepseek}"

echo "Starting ant-colony gateway on $HOST:$PORT (profile=$PROFILE) ..."
exec python3 -c "
import logging, sys
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
from src.gateway.webhook_server import serve
serve('$HOST', $PORT, '$PROFILE')
"
