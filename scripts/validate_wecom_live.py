from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen


DEFAULT_ENV_FILE = "infra/.env.wecom"
DEFAULT_WS_URL = "wss://openws.work.weixin.qq.com"


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


def fetch_wecom_access_token(values: dict[str, str]) -> dict[str, Any]:
    corp_id = values.get("WECOM_CORP_ID", "")
    secret = values.get("WECOM_SECRET", "")
    if not corp_id or not secret:
        return {"ok": False, "configured": False, "reason": "missing WECOM_CORP_ID or WECOM_SECRET"}
    url = (
        "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
        f"?corpid={quote(corp_id)}&corpsecret={quote(secret)}"
    )
    with urlopen(Request(url), timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("errcode", 0) != 0:
        return {"ok": False, "configured": True, "reason": payload.get("errmsg", "unknown")}
    token = str(payload.get("access_token", ""))
    return {
        "ok": True,
        "configured": True,
        "token_prefix": token[:3] + "***" if token else "",
        "expires_in": payload.get("expires_in", 0),
    }


async def validate_wecom_bot_websocket(values: dict[str, str]) -> dict[str, Any]:
    bot_id = values.get("WECOM_BOT_ID", "")
    secret = values.get("WECOM_BOT_SECRET", "")
    ws_url = values.get("WECOM_WEBSOCKET_URL", DEFAULT_WS_URL)
    if not bot_id or not secret:
        return {"ok": False, "configured": False, "reason": "missing WECOM_BOT_ID or WECOM_BOT_SECRET"}
    try:
        import websockets
        from uuid import uuid4

        async with websockets.connect(ws_url, ping_interval=None, ping_timeout=None, close_timeout=5) as ws:
            frame = {
                "cmd": "aibot_subscribe",
                "headers": {"req_id": str(uuid4())},
                "body": {"bot_id": bot_id, "secret": secret, "device_id": "codex-live-check"},
            }
            await ws.send(json.dumps(frame))
            raw = await asyncio.wait_for(ws.recv(), timeout=15)
            payload = json.loads(raw)
            if payload.get("errcode", -1) != 0:
                return {"ok": False, "configured": True, "ws_url": ws_url, "reason": str(payload)}
            return {"ok": True, "configured": True, "ws_url": ws_url}
    except Exception as exc:
        return {"ok": False, "configured": True, "ws_url": ws_url, "reason": str(exc)}


async def validate_wecom_configuration(values: dict[str, str]) -> dict[str, Any]:
    return {
        "corp_api": fetch_wecom_access_token(values),
        "bot_ws": await validate_wecom_bot_websocket(values),
    }


def wecom_configuration_ok(report: dict[str, Any]) -> bool:
    return bool(report.get("corp_api", {}).get("ok") and report.get("bot_ws", {}).get("ok"))


async def _async_main() -> int:
    values = dict(load_env_file(DEFAULT_ENV_FILE))
    for key in (
        "WECOM_CORP_ID",
        "WECOM_SECRET",
        "WECOM_BOT_ID",
        "WECOM_BOT_SECRET",
        "WECOM_WEBSOCKET_URL",
    ):
        if os.environ.get(key):
            values[key] = os.environ[key]
    report = await validate_wecom_configuration(values)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if wecom_configuration_ok(report) else 1


def main() -> int:
    return asyncio.run(_async_main())


if __name__ == "__main__":
    raise SystemExit(main())
