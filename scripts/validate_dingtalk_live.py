from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


DEFAULT_ENV_FILE = "infra/.env.wecom"


def load_env_file(path: str = DEFAULT_ENV_FILE) -> dict[str, str]:
    values: dict[str, str] = {}
    env_path = Path(path)
    if not env_path.exists():
        return values
    for raw_line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def fetch_dingtalk_token(values: dict[str, str]) -> dict[str, Any]:
    client_id = values.get("DINGTALK_CLIENT_ID", "")
    secret = values.get("DINGTALK_CLIENT_SECRET", "")
    if not client_id or not secret:
        return {"ok": False, "configured": False, "reason": "missing DINGTALK_CLIENT_ID or DINGTALK_CLIENT_SECRET"}
    url = f"https://oapi.dingtalk.com/gettoken?appkey={client_id}&appsecret={secret}"
    req = Request(url, method="GET")
    with urlopen(req, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("errcode", -1) != 0:
        return {"ok": False, "configured": True, "reason": payload.get("errmsg", "unknown")}
    token = str(payload.get("access_token", ""))
    return {"ok": True, "configured": True, "token_prefix": token[:3] + "***" if token else ""}


async def validate_dingtalk_configuration(values: dict[str, str]) -> dict[str, Any]:
    return {"api": fetch_dingtalk_token(values)}


def dingtalk_configuration_ok(report: dict[str, Any]) -> bool:
    return bool(report.get("api", {}).get("ok"))


def main() -> int:
    values = dict(load_env_file(DEFAULT_ENV_FILE))
    for key in ("DINGTALK_CLIENT_ID", "DINGTALK_CLIENT_SECRET"):
        if os.environ.get(key):
            values[key] = os.environ[key]
    report = asyncio.run(validate_dingtalk_configuration(values))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if os.environ.get("ANT_COLONY_VALIDATE_ALLOW_UNCONFIGURED", "").strip().lower() in {"1", "true", "yes"} and not report.get("api", {}).get("configured"):
        return 0
    return 0 if dingtalk_configuration_ok(report) else 1


if __name__ == "__main__":
    raise SystemExit(main())
