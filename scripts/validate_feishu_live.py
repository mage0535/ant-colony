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


def fetch_feishu_token(values: dict[str, str]) -> dict[str, Any]:
    app_id = values.get("FEISHU_APP_ID", "")
    secret = values.get("FEISHU_APP_SECRET", "")
    if not app_id or not secret:
        return {"ok": False, "configured": False, "reason": "missing FEISHU_APP_ID or FEISHU_APP_SECRET"}
    body = json.dumps({"app_id": app_id, "app_secret": secret}).encode("utf-8")
    req = Request(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urlopen(req, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("code", -1) != 0:
        return {"ok": False, "configured": True, "reason": payload.get("msg", "unknown")}
    token = str(payload.get("tenant_access_token", ""))
    return {"ok": True, "configured": True, "token_prefix": token[:3] + "***" if token else ""}


async def validate_feishu_configuration(values: dict[str, str]) -> dict[str, Any]:
    return {"api": fetch_feishu_token(values)}


def feishu_configuration_ok(report: dict[str, Any]) -> bool:
    return bool(report.get("api", {}).get("ok"))


def main() -> int:
    values = dict(load_env_file(DEFAULT_ENV_FILE))
    for key in ("FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_DOMAIN"):
        if os.environ.get(key):
            values[key] = os.environ[key]
    report = asyncio.run(validate_feishu_configuration(values))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if os.environ.get("ANT_COLONY_VALIDATE_ALLOW_UNCONFIGURED", "").strip().lower() in {"1", "true", "yes"} and not report.get("api", {}).get("configured"):
        return 0
    return 0 if feishu_configuration_ok(report) else 1


if __name__ == "__main__":
    raise SystemExit(main())
