from __future__ import annotations

import os
from functools import wraps
from pathlib import Path
from typing import Any, Callable

_ENV_FILE_CANDIDATES = [
    Path("infra/.env.langsmith"),
    Path(__file__).resolve().parents[2] / "infra" / ".env.langsmith",
    Path(os.environ.get("ANT_COLONY_HOME", "")) / "infra" / ".env.langsmith" if os.environ.get("ANT_COLONY_HOME") else Path(),
]


def _load_env_file() -> dict[str, str]:
    values: dict[str, str] = {}
    for path in _ENV_FILE_CANDIDATES:
        if not path.is_file():
            continue
        for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
        break
    return values


def configure_langsmith_env() -> dict[str, str]:
    values = _load_env_file()
    for key, value in values.items():
        os.environ.setdefault(key, value)
    os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ.setdefault("LANGSMITH_PROJECT", "ant-colony")
    return values


def langsmith_enabled() -> bool:
    configure_langsmith_env()
    return bool(os.environ.get("LANGSMITH_API_KEY")) and os.environ.get("LANGSMITH_TRACING", "").lower() == "true"


def get_langsmith_client():
    configure_langsmith_env()
    if not langsmith_enabled():
        return None
    try:
        from langsmith import Client

        kwargs: dict[str, Any] = {"api_key": os.environ.get("LANGSMITH_API_KEY", "")}
        if os.environ.get("LANGSMITH_ENDPOINT"):
            kwargs["api_url"] = os.environ["LANGSMITH_ENDPOINT"]
        return Client(**kwargs)
    except Exception:
        return None


def ensure_langsmith_project(project_name: str = "ant-colony") -> bool:
    client = get_langsmith_client()
    if client is None:
        return False
    try:
        if not client.has_project(project_name=project_name):
            client.create_project(project_name=project_name)
        return True
    except Exception:
        return False


def traceable_op(name: str, run_type: str = "chain") -> Callable:
    configure_langsmith_env()
    if not langsmith_enabled():
        def _noop(func: Callable) -> Callable:
            return func
        return _noop
    try:
        from langsmith import traceable

        return traceable(name=name, run_type=run_type)
    except Exception:
        def _fallback(func: Callable) -> Callable:
            return func
        return _fallback


def wrap_openai_client(client):
    if not langsmith_enabled():
        return client
    if client.__class__.__module__.startswith("unittest.mock"):
        return client
    try:
        from langsmith.wrappers import wrap_openai

        return wrap_openai(client)
    except Exception:
        return client


def wrap_anthropic_client(client):
    if not langsmith_enabled():
        return client
    if client.__class__.__module__.startswith("unittest.mock"):
        return client
    try:
        from langsmith.wrappers import wrap_anthropic

        return wrap_anthropic(client)
    except Exception:
        return client
