#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE="./external/openvort/source/.env"

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "FAIL: neither python3 nor python is available."
  exit 1
fi

declare -A ENV_MAP

load_env_file() {
  local path="$1"
  [[ -f "$path" ]] || return 0

  while IFS= read -r line; do
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" || "${line:0:1}" == "#" ]] && continue
    if [[ "$line" == *"="* ]]; then
      local key="${line%%=*}"
      local value="${line#*=}"
      ENV_MAP["$key"]="$value"
    fi
  done < "$path"
}

get_config_value() {
  local key="$1"
  if [[ -n "${!key:-}" ]]; then
    printf '%s' "${!key}"
    return
  fi
  if [[ -n "${ENV_MAP[$key]:-}" ]]; then
    printf '%s' "${ENV_MAP[$key]}"
    return
  fi
  printf ''
}

is_meaningful_value() {
  local value="${1:-}"
  [[ -n "$value" ]] || return 1

  local normalized
  normalized="$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')"

  [[ "$normalized" == replace-with-* ]] && return 1
  [[ "$normalized" == your-* ]] && return 1
  [[ "$normalized" == example-* ]] && return 1

  case "$normalized" in
    admin|changeme|todo|tbd)
      return 1
      ;;
  esac

  return 0
}

tcp_reachable() {
  local host="$1"
  local port="$2"
  "$PYTHON_BIN" - "$host" "$port" <<'PY'
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(2)
try:
    s.connect((host, port))
except OSError:
    print("false")
else:
    print("true")
finally:
    s.close()
PY
}

load_env_file "$ENV_FILE"

database_url="$(get_config_value OPENVORT_DATABASE_URL)"
if [[ -z "$database_url" ]]; then
  database_url="postgresql+asyncpg://openvort:openvort@localhost:5432/openvort"
fi

llm_api_key="$(get_config_value OPENVORT_LLM_API_KEY)"
admin_ids="$(get_config_value OPENVORT_CONTACTS_ADMIN_USER_IDS)"
web_password="$(get_config_value OPENVORT_WEB_DEFAULT_PASSWORD)"
if [[ -z "$web_password" ]]; then
  web_password="admin"
fi

db_host="localhost"
db_port="5432"
if [[ "$database_url" =~ @([^:/]+)(:([0-9]+))?/ ]]; then
  db_host="${BASH_REMATCH[1]}"
  if [[ -n "${BASH_REMATCH[3]:-}" ]]; then
    db_port="${BASH_REMATCH[3]}"
  fi
fi

wecom_keys=(
  OPENVORT_WECOM_CORP_ID
  OPENVORT_WECOM_APP_SECRET
  OPENVORT_WECOM_AGENT_ID
  OPENVORT_WECOM_CALLBACK_TOKEN
  OPENVORT_WECOM_CALLBACK_AES_KEY
)

missing_wecom=()
for key in "${wecom_keys[@]}"; do
  value="$(get_config_value "$key")"
  if ! is_meaningful_value "$value"; then
    missing_wecom+=("$key")
  fi
done

if command -v docker >/dev/null 2>&1; then
  docker_available=true
else
  docker_available=false
fi

db_reachable="$(tcp_reachable "$db_host" "$db_port")"
if is_meaningful_value "$llm_api_key"; then
  llm_configured=true
else
  llm_configured=false
fi
if is_meaningful_value "$admin_ids"; then
  admin_configured=true
else
  admin_configured=false
fi
if is_meaningful_value "$web_password" && [[ "$web_password" != "admin" ]]; then
  web_password_customized=true
else
  web_password_customized=false
fi

echo "== OpenVort prerequisite check (Linux) =="
if [[ -f "$ENV_FILE" ]]; then
  echo "Config source: ./external/openvort/source/.env"
else
  echo "Config source: (falling back to process env + defaults)"
fi
echo "Database URL: $database_url"
echo "Database reachable: $db_reachable"
echo "Docker available: $docker_available"
echo "LLM API key configured: $llm_configured"
echo "Admin user ids configured: $admin_configured"
echo "Web default password customized: $web_password_customized"
if [[ ${#missing_wecom[@]} -eq 0 ]]; then
  echo "WeCom config complete: true"
else
  echo "WeCom config complete: false"
  echo "Missing WeCom keys:"
  for key in "${missing_wecom[@]}"; do
    echo "  - $key"
  done
fi

echo
echo "Recommended next steps:"
if [[ "$db_reachable" != "true" ]]; then
  if [[ "$docker_available" == "true" ]]; then
    echo "- Provide a reachable PostgreSQL service or let OpenVort auto-start Docker-backed PostgreSQL."
  else
    echo "- Install Docker or point OPENVORT_DATABASE_URL at an already running PostgreSQL instance."
  fi
fi
if [[ "$llm_configured" != "true" ]]; then
  echo "- Set OPENVORT_LLM_API_KEY before expecting LLM-backed behavior."
fi
if [[ "$admin_configured" != "true" ]]; then
  echo "- Set OPENVORT_CONTACTS_ADMIN_USER_IDS for contact/admin operations."
fi
if [[ "$web_password_customized" != "true" ]]; then
  echo "- Override OPENVORT_WEB_DEFAULT_PASSWORD with a stronger value."
fi
if [[ ${#missing_wecom[@]} -gt 0 ]]; then
  echo "- Fill the required OPENVORT_WECOM_* values before testing the wecom channel."
fi
