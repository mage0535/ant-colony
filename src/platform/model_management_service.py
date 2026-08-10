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
    profiles = service.build_llm_views()
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
                "is_default": _is_default_profile(view),
            }
            for view in profiles
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
    view["is_default"] = _is_default_profile(record)
    view.pop("api_key", None)
    if not _has_default_profile(service.list_llm_profiles()):
        set_default_model_profile(record.profile_id)
        updated = service.get_llm_profile(record.profile_id)
        if updated is not None:
            view["metadata"] = updated.metadata
            view["is_default"] = _is_default_profile(updated)
    return view


def set_default_model_profile(profile_id: str) -> dict[str, Any]:
    service = build_settings_service()
    profiles = service.list_llm_profiles()
    target = next((item for item in profiles if item.profile_id == profile_id), None)
    if target is None:
        raise ValueError("未找到模型配置")
    if not target.enabled:
        raise ValueError("只能将启用中的模型设为默认模型")
    for profile in profiles:
        metadata = dict(profile.metadata or {})
        should_be_default = profile.profile_id == profile_id
        if bool(metadata.get("is_default")) == should_be_default:
            continue
        metadata["is_default"] = should_be_default
        service.upsert_llm_profile(
            profile_id=profile.profile_id,
            provider=profile.provider,
            model_name=profile.model_name,
            api_key=None,
            api_base=profile.api_base,
            max_tokens=profile.max_tokens,
            timeout_seconds=profile.timeout_seconds,
            enabled=profile.enabled,
            metadata=metadata,
        )
    updated = service.get_llm_profile(profile_id)
    return {
        "ok": True,
        "profile_id": profile_id,
        "is_default": True,
        "model_name": updated.model_name if updated else target.model_name,
    }


def delete_model_profile(profile_id: str) -> dict[str, Any]:
    normalized_id = str(profile_id or "").strip()
    if not normalized_id:
        raise ValueError("缺少模型配置名称")
    service = build_settings_service()
    target = service.get_llm_profile(normalized_id)
    if target is None:
        raise ValueError("未找到模型配置")
    was_default = _is_default_profile(target)
    if not service.delete_llm_profile(normalized_id):
        raise ValueError("未找到模型配置")
    if was_default:
        remaining_enabled = [profile for profile in service.list_llm_profiles() if profile.enabled]
        if remaining_enabled:
            set_default_model_profile(remaining_enabled[0].profile_id)
    return {"ok": True, "profile_id": normalized_id, "deleted": True}


def discover_models(payload: dict[str, Any]) -> dict[str, Any]:
    provider = str(payload.get("provider") or "openai").lower()
    sdk_format = str(payload.get("sdk_format") or provider or "openai").lower()
    api_base = str(payload.get("api_base") or "").strip()
    api_key = str(payload.get("api_key") or "").strip()
    if not api_key:
        return {"ok": False, "models": [], "message": "缺少 API Key，无法自动读取模型清单"}
    if "anthropic" in sdk_format or "anthropic" in provider:
        return _discover_anthropic_models(api_base, api_key)
    return _discover_openai_models(api_base, api_key, provider=provider)


def _discover_openai_models(api_base: str, api_key: str, *, provider: str = "openai") -> dict[str, Any]:
    endpoint = _openai_models_endpoint(api_base, provider=provider)
    req = urllib.request.Request(endpoint, method="GET")
    _add_model_discovery_headers(req, api_key=api_key, sdk_format="openai")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return _model_discovery_error(exc, endpoint=endpoint, provider=provider, sdk_format="openai")
    except (urllib.error.URLError, TimeoutError) as exc:
        return {"ok": False, "models": [], "message": f"自动读取失败：无法连接模型服务商（{exc}）。请检查服务商 URL、网络和代理；如果服务商不支持读取模型清单，可以手工填写模型 ID 后保存。"}
    models = []
    for item in data.get("data", []):
        model_id = _normalize_discovered_model_id(str(item.get("id") or ""), endpoint=endpoint)
        if model_id:
            models.append({"id": model_id, "name": str(item.get("name") or item.get("display_name") or model_id)})
    return {"ok": True, "models": models, "message": f"读取到 {len(models)} 个模型"}


def _discover_anthropic_models(api_base: str, api_key: str) -> dict[str, Any]:
    base = api_base.rstrip("/") if api_base else "https://api.anthropic.com/v1"
    if not base.endswith("/v1") and "/v1" not in base:
        base = base + "/v1"
    endpoint = base.rstrip("/") + "/models"
    req = urllib.request.Request(endpoint, method="GET")
    _add_model_discovery_headers(req, api_key=api_key, sdk_format="anthropic")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return _model_discovery_error(exc, endpoint=endpoint, provider="anthropic", sdk_format="anthropic")
    except (urllib.error.URLError, TimeoutError) as exc:
        return {"ok": False, "models": [], "message": f"自动读取失败：无法连接模型服务商（{exc}）。请检查服务商 URL、网络和代理；如果服务商不支持读取模型清单，可以手工填写模型 ID 后保存。"}
    models = []
    for item in data.get("data", []):
        model_id = str(item.get("id") or item.get("name") or "")
        if model_id:
            models.append({"id": model_id, "name": str(item.get("display_name") or model_id)})
    return {"ok": True, "models": models, "message": f"读取到 {len(models)} 个模型"}


def _default_openai_base(provider: str) -> str:
    normalized = str(provider or "").strip().lower()
    if normalized == "deepseek":
        return "https://api.deepseek.com/v1"
    return "https://api.openai.com/v1"


def _openai_models_endpoint(api_base: str, *, provider: str = "openai") -> str:
    base = api_base.rstrip("/") if api_base else _default_openai_base(provider)
    if base.rstrip("/").endswith("/models"):
        return base
    if not base.endswith("/v1") and "/v1" not in base:
        base = base + "/v1"
    return base.rstrip("/") + "/models"


def _normalize_discovered_model_id(model_id: str, *, endpoint: str) -> str:
    value = str(model_id or "").strip()
    if not value:
        return ""
    return value


def normalize_model_name_for_api(model_name: str, api_base: str = "") -> str:
    """Normalize display/config model IDs to the provider API model field."""
    value = str(model_name or "").strip()
    base = str(api_base or "").strip().lower()
    if "opencode.ai/zen/" in base or base.rstrip("/") == "https://opencode.ai/zen/v1":
        return value.removeprefix("opencode/")
    return value


def _add_model_discovery_headers(req: urllib.request.Request, *, api_key: str, sdk_format: str) -> None:
    # Some providers, including OpenCode Zen behind Cloudflare, reject Python's
    # default urllib signature even for public model-list endpoints.
    req.add_header("User-Agent", "Ant-Colony-AI-Assistant/1.0")
    req.add_header("Accept", "application/json, text/plain, */*")
    req.add_header("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.8")
    if sdk_format == "anthropic":
        req.add_header("x-api-key", api_key)
        req.add_header("anthropic-version", "2023-06-01")
    else:
        req.add_header("Authorization", f"Bearer {api_key}")


def _model_discovery_error(
    exc: urllib.error.HTTPError,
    *,
    endpoint: str,
    provider: str,
    sdk_format: str,
) -> dict[str, Any]:
    body = ""
    try:
        body = exc.read().decode("utf-8", "replace")[:500]
    except Exception:
        body = ""
    status = getattr(exc, "code", None) or "?"
    reason = getattr(exc, "reason", "") or ""
    if int(status) in {401, 403}:
        message = (
            f"自动读取失败：服务商拒绝读取模型清单（HTTP {status} {reason}）。"
            "这通常不代表聊天接口不可用，常见原因是：服务商不开放 /models 接口、API Key 没有列模型权限、服务商 URL 填错，或 SDK 格式选择不匹配。"
            "请先确认“服务商 URL”和“SDK 格式”，也可以直接在“模型名称 / ID”中手工填写模型 ID 后保存。"
            f"本次尝试地址：{endpoint}"
        )
        if body:
            message += f"；服务商返回：{body}"
        return {
            "ok": False,
            "models": [],
            "message": message,
            "manual_entry_supported": True,
            "status_code": int(status),
            "provider": provider,
            "sdk_format": sdk_format,
            "endpoint": endpoint,
        }
    message = f"自动读取失败：HTTP {status} {reason}。请检查服务商 URL、API Key 和 SDK 格式；如果服务商不支持读取模型清单，可以手工填写模型 ID 后保存。"
    if body:
        message += f" 服务商返回：{body}"
    return {
        "ok": False,
        "models": [],
        "message": message,
        "manual_entry_supported": True,
        "status_code": int(status) if str(status).isdigit() else status,
        "provider": provider,
        "sdk_format": sdk_format,
        "endpoint": endpoint,
    }


def _coerce_provider(value: str) -> LLMProvider:
    normalized = value.strip().lower()
    if normalized in {"openai", "openai_compatible", "anthropic", "deepseek"}:
        return LLMProvider(normalized)
    if "anthropic" in normalized:
        return LLMProvider.ANTHROPIC
    return LLMProvider.OPENAI_COMPATIBLE


def _is_default_profile(profile: Any) -> bool:
    metadata = getattr(profile, "metadata", None) or {}
    return bool(metadata.get("is_default"))


def _has_default_profile(profiles: list[Any]) -> bool:
    return any(_is_default_profile(profile) for profile in profiles)
