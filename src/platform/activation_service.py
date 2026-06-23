from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.config.bootstrap import build_settings_service
from src.config.contracts import PlatformType
from src.platform.bot_setup import write_env_values


ENV_KEY_MAPPINGS: dict[str, dict[str, str]] = {
    "wecom": {
        "bot_id": "WECOM_BOT_ID",
        "bot_secret": "WECOM_BOT_SECRET",
        "corp_id": "WECOM_CORP_ID",
        "agent_id": "WECOM_AGENT_ID",
        "secret": "WECOM_SECRET",
        "callback_token": "WECOM_CALLBACK_TOKEN",
        "callback_aes_key": "WECOM_CALLBACK_AES_KEY",
    },
    "feishu": {
        "app_id": "FEISHU_APP_ID",
        "app_secret": "FEISHU_APP_SECRET",
        "domain": "FEISHU_DOMAIN",
    },
    "dingtalk": {
        "client_id": "DINGTALK_CLIENT_ID",
        "client_secret": "DINGTALK_CLIENT_SECRET",
        "robot_code": "DINGTALK_ROBOT_CODE",
    },
}

ENV_KEY_ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    "dingtalk": {
        "client_id": ("DINGTALK_APP_KEY",),
        "client_secret": ("DINGTALK_APP_SECRET",),
    },
}

REQUIRED_CREDENTIALS: dict[str, tuple[str, ...]] = {
    "wecom": ("bot_id", "bot_secret"),
    "feishu": ("app_id", "app_secret"),
    "dingtalk": ("client_id", "client_secret", "robot_code"),
}

SETTINGS_KEY_MAPPINGS: dict[str, dict[str, str]] = {
    "wecom": {
        "corp_id": "corp_id",
        "agent_id": "agent_id",
        "secret": "secret",
        "callback_token": "callback_token",
        "callback_aes_key": "callback_aes_key",
        "bot_id": "bot_id",
        "bot_secret": "bot_secret",
    },
    "feishu": {
        "app_id": "app_id",
        "app_secret": "app_secret",
        "domain": "domain",
    },
    "dingtalk": {
        "client_id": "app_key",
        "client_secret": "app_secret",
        "robot_code": "robot_code",
    },
}


@dataclass(slots=True)
class ActivationResult:
    platform: str
    enabled: bool
    managed_by_platform: bool
    configured_keys: list[str]
    env_file: str
    visibility_scope: str
    display_name: str
    auto_permissions: list[str]
    restart_required: bool
    next_action: str


def activate_platform_bot(
    *,
    platform: str,
    credentials: dict[str, str],
    activated_by: str = "",
    display_name: str = "",
    visibility_scope: str = "all",
    auto_permissions: list[str] | None = None,
    env_file: str | Path = "infra/.env.wecom",
) -> ActivationResult:
    normalized_platform = platform.strip().lower()
    if normalized_platform not in ENV_KEY_MAPPINGS:
        raise ValueError(f"Unsupported platform: {platform}")
    missing_credentials = _missing_required_credentials(normalized_platform, credentials)
    if missing_credentials:
        readable = ", ".join(missing_credentials)
        raise ValueError(f"{_platform_label(normalized_platform)}统一开通缺少必填凭据：{readable}")

    auto_permissions = auto_permissions or ["docs.full", "knowledge.readwrite", "contacts.read"]
    env_map = _build_env_map(normalized_platform, credentials)
    if env_map:
        write_env_values(env_file, env_map)

    settings_map = {
        settings_key: str(credentials.get(source_key, "")).strip()
        for source_key, settings_key in SETTINGS_KEY_MAPPINGS[normalized_platform].items()
        if str(credentials.get(source_key, "")).strip()
    }
    metadata = {
        "managed_by_platform": True,
        "activation_mode": "centralized",
        "user_self_service": False,
        "callback_managed_by_platform": True,
        "display_name": display_name or _default_display_name(normalized_platform),
        "visibility_scope": visibility_scope,
        "activated_by": activated_by,
        "auto_permissions": auto_permissions,
    }

    service = build_settings_service()
    service.upsert_platform_settings(
        platform=_platform_type(normalized_platform),
        enabled=True,
        settings=settings_map,
        metadata=metadata,
    )
    restart_required = _restart_required(normalized_platform, env_map)

    return ActivationResult(
        platform=normalized_platform,
        enabled=True,
        managed_by_platform=True,
        configured_keys=sorted(settings_map.keys()),
        env_file=str(env_file),
        visibility_scope=visibility_scope,
        display_name=metadata["display_name"],
        auto_permissions=list(auto_permissions),
        restart_required=restart_required,
        next_action=_next_action(normalized_platform, restart_required),
    )


def list_platform_bot_statuses() -> list[dict[str, Any]]:
    service = build_settings_service()
    views = {view.platform.value: view for view in service.build_platform_views()}
    statuses: list[dict[str, Any]] = []
    for platform in ("wecom", "feishu", "dingtalk"):
        record = service.get_platform_settings(_platform_type(platform))
        view = views.get(platform)
        metadata = dict(record.metadata) if record else {}
        platform_enabled = bool(record.enabled) if record else False
        required_env_keys = _required_env_keys(platform)
        missing_process_env = [key for key in required_env_keys if not os.environ.get(key)]
        restart_required = platform_enabled and bool(missing_process_env)
        missing_keys = view.missing_keys if view else []
        statuses.append(
            {
                "platform": platform,
                "platform_label": _platform_label(platform),
                "enabled": platform_enabled,
                "configured_keys": view.configured_keys if view else [],
                "missing_keys": missing_keys,
                "required_env_keys": required_env_keys,
                "missing_process_env": missing_process_env,
                "restart_required": restart_required,
                "next_action": _status_next_action(platform, platform_enabled, missing_keys, restart_required),
                "managed_by_platform": bool(metadata.get("managed_by_platform")),
                "user_self_service": bool(metadata.get("user_self_service")) if metadata else False,
                "callback_managed_by_platform": bool(metadata.get("callback_managed_by_platform")) if metadata else False,
                "display_name": str(metadata.get("display_name", _default_display_name(platform))),
                "visibility_scope": str(metadata.get("visibility_scope", "")),
                "auto_permissions": metadata.get("auto_permissions", []),
            }
        )
    return statuses


def _platform_type(platform: str) -> PlatformType:
    return {
        "wecom": PlatformType.WECOM,
        "feishu": PlatformType.FEISHU,
        "dingtalk": PlatformType.DINGTALK,
    }[platform]


def _default_display_name(platform: str) -> str:
    return {
        "wecom": "企业 AI 助手",
        "feishu": "飞书 AI 助手",
        "dingtalk": "钉钉 AI 助手",
    }.get(platform, "企业 AI 助手")


def _platform_label(platform: str) -> str:
    return {
        "wecom": "企业微信",
        "feishu": "飞书",
        "dingtalk": "钉钉",
    }.get(platform, platform)


def _missing_required_credentials(platform: str, credentials: dict[str, str]) -> list[str]:
    return [
        key
        for key in REQUIRED_CREDENTIALS[platform]
        if not str(credentials.get(key, "")).strip()
    ]


def _build_env_map(platform: str, credentials: dict[str, str]) -> dict[str, str]:
    env_map: dict[str, str] = {}
    for source_key, env_key in ENV_KEY_MAPPINGS[platform].items():
        value = str(credentials.get(source_key, "")).strip()
        if not value:
            continue
        env_map[env_key] = value
        for alias in ENV_KEY_ALIASES.get(platform, {}).get(source_key, ()):
            env_map[alias] = value
    return env_map


def _required_env_keys(platform: str) -> list[str]:
    keys: list[str] = []
    for source_key in REQUIRED_CREDENTIALS[platform]:
        env_key = ENV_KEY_MAPPINGS[platform].get(source_key)
        if env_key:
            keys.append(env_key)
    return keys


def _restart_required(platform: str, written_env: dict[str, str]) -> bool:
    for key in _required_env_keys(platform):
        if key in written_env and os.environ.get(key) != written_env[key]:
            return True
    return False


def _next_action(platform: str, restart_required: bool) -> str:
    label = _platform_label(platform)
    if restart_required:
        return f"{label}凭据已保存，重启对应 Bot/网关服务后生效。"
    return f"{label}凭据已在当前运行环境中生效，可继续做消息链路测试。"


def _status_next_action(platform: str, enabled: bool, missing_keys: list[str], restart_required: bool) -> str:
    label = _platform_label(platform)
    if not enabled:
        return f"{label}尚未通过平台管理页统一开通。"
    if missing_keys:
        return f"{label}已启用但缺少配置：{', '.join(missing_keys)}。请补齐后重新保存。"
    return _next_action(platform, restart_required)
