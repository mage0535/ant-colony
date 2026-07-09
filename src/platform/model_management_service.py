from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import asdict
from typing import Any

from src.config.bootstrap import build_settings_service
from src.config.contracts import LLMProvider


def list_model_profiles() -> dict[str, Any]:
    service = build_settings_service()
    return {
        "profiles": [
            {
                "profile_id": view.profile_id,
                "provider": view.provider.value,
                "model_name": view.model_name,
                "api_base": view.api_base or "",
                "api_key_configured": view.api_key_configured,
                "max_tokens": view.max_tokens,
                "timeout_seconds": view.timeout_seconds,
                "enabled": view.enabled,
                "metadata": view.metadata,
            }
            for view in service.build_llm_views()
        ]
    }


def save_model_profile(payload: dict[str, Any]) -> dict[str, Any]:
    provider = _coerce_provider(str(payload.get("provider") or "openai_compatible"))
    profile_id = str(payload.get("profile_id") or "").strip()
    model_name = str(payload.get("model_name") or "").strip()
    if not profile_id:
        raise ValueError("缺少模型配置名称")
    if not model_name:
        raise ValueError("缺少模型名称或模型 ID")
    service = build_settings_service()
    existing = service.get_llm_profile(profile_id)
    api_key = payload.get("api_key")
    if api_key == "" and existing:
        api_key = None
    record = service.upsert_llm_profile(
        profile_id=profile_id,
        provider=provider,
        model_name=model_name,
        api_key=api_key,
        api_base=str(payload.get("api_base") or "").strip() or None,
        max_tokens=int(payload.get("max_tokens") or 4096),
        timeout_seconds=int(payload.get("timeout_seconds") or 120),
        enabled=bool(payload.get("enabled", True)),
        metadata={
            "sdk_format": str(payload.get("sdk_format") or provider.value),
            "display_name": str(payload.get("display_name") or profile_id),
            "updated_at": time.time(),
        },
    )
    view = asdict(record)
    view["provider"] = record.provider.value
    view["api_key_configured"] = bool(record.api_key)
    view.pop("api_key", None)
    return view


def discover_models(payload: dict[str, Any]) -> dict[str, Any]:
    provider = str(payload.get("provider") or payload.get("sdk_format") or "openai").lower()
    api_base = str(payload.get("api_base") or "").strip()
    api_key = str(payload.get("api_key") or "").strip()
    if not api_key:
        return {"ok": False, "models": [], "message": "缺少 API Key，无法自动读取模型清单"}
    if "anthropic" in provider:
        return _discover_anthropic_models(api_base, api_key)
    return _discover_openai_models(api_base, api_key)


def _discover_openai_models(api_base: str, api_key: str) -> dict[str, Any]:
    base = api_base.rstrip("/") if api_base else "https://api.openai.com/v1"
    if not base.endswith("/v1") and "/v1" not in base:
        base = base + "/v1"
    req = urllib.request.Request(base.rstrip("/") + "/models", method="GET")
    req.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        return {"ok": False, "models": [], "message": f"自动读取失败：{exc}"}
    models = []
    for item in data.get("data", []):
        model_id = str(item.get("id") or "")
        if model_id:
            models.append({"id": model_id, "name": model_id})
    return {"ok": True, "models": models, "message": f"读取到 {len(models)} 个模型"}


def _discover_anthropic_models(api_base: str, api_key: str) -> dict[str, Any]:
    base = api_base.rstrip("/") if api_base else "https://api.anthropic.com/v1"
    if not base.endswith("/v1") and "/v1" not in base:
        base = base + "/v1"
    req = urllib.request.Request(base.rstrip("/") + "/models", method="GET")
    req.add_header("x-api-key", api_key)
    req.add_header("anthropic-version", "2023-06-01")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        return {"ok": False, "models": [], "message": f"自动读取失败：{exc}"}
    models = []
    for item in data.get("data", []):
        model_id = str(item.get("id") or item.get("name") or "")
        if model_id:
            models.append({"id": model_id, "name": str(item.get("display_name") or model_id)})
    return {"ok": True, "models": models, "message": f"读取到 {len(models)} 个模型"}


def _coerce_provider(value: str) -> LLMProvider:
    normalized = value.strip().lower()
    if normalized in {"openai", "openai_compatible", "anthropic", "deepseek"}:
        return LLMProvider(normalized)
    if "anthropic" in normalized:
        return LLMProvider.ANTHROPIC
    return LLMProvider.OPENAI_COMPATIBLE
