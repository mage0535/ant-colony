from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import Any


PLATFORM_ENV = {
    "wecom": ("WECOM_BOT_ID", "WECOM_BOT_SECRET"),
    "feishu": ("FEISHU_APP_ID", "FEISHU_APP_SECRET"),
    "dingtalk": ("DINGTALK_CLIENT_ID", "DINGTALK_CLIENT_SECRET"),
}

SERVICE_PORTS = {
    "gateway": 18090,
    "callback": 18091,
    "dashboard": 18092,
    "gbrain": 8787,
    "hindsight": 8890,
    "embed": 8766,
}

ENV_FILES = [
    Path(".env.wecom"),
    Path("infra/.env.wecom"),
    Path("data/openvort_runtime.env"),
]


def collect_runtime_validation_report() -> dict[str, Any]:
    env_file_values = _load_env_files()
    return {
        "platforms": {
            name: _platform_status(name, keys, env_file_values)
            for name, keys in PLATFORM_ENV.items()
        },
        "ports": {name: _probe_port(port) for name, port in SERVICE_PORTS.items()},
    }


def _platform_status(name: str, keys: tuple[str, ...], env_file_values: dict[str, str]) -> dict[str, Any]:
    process_present = [key for key in keys if os.environ.get(key)]
    file_present = [key for key in keys if env_file_values.get(key)]
    configured = len(process_present) == len(keys) or len(file_present) == len(keys)
    source = "process_env" if len(process_present) == len(keys) else "env_file" if len(file_present) == len(keys) else "missing"
    present = process_present if source == "process_env" else file_present
    missing = [key for key in keys if key not in present]
    return {
        "configured": configured,
        "required_env": list(keys),
        "present_env": present,
        "missing_env": missing,
        "source": source,
    }


def _load_env_files() -> dict[str, str]:
    values: dict[str, str] = {}
    for path in ENV_FILES:
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def _probe_port(port: int) -> dict[str, Any]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.5)
    try:
        sock.connect(("127.0.0.1", port))
        return {"reachable": True, "port": port}
    except OSError as exc:
        return {"reachable": False, "port": port, "error": str(exc)}
    finally:
        sock.close()


def main() -> int:
    print(json.dumps(collect_runtime_validation_report(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
