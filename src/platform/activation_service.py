from __future__ import annotations

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

    auto_permissions = auto_permissions or ["docs.full", "knowledge.readwrite", "contacts.read"]
    env_map = {
        env_key: str(credentials.get(source_key, "")).strip()
        for source_key, env_key in ENV_KEY_MAPPINGS[normalized_platform].items()
        if str(credentials.get(source_key, "")).strip()
    }
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

    return ActivationResult(
        platform=normalized_platform,
        enabled=True,
        managed_by_platform=True,
        configured_keys=sorted(settings_map.keys()),
        env_file=str(env_file),
        visibility_scope=visibility_scope,
        display_name=metadata["display_name"],
        auto_permissions=list(auto_permissions),
    )


def list_platform_bot_statuses() -> list[dict[str, Any]]:
    service = build_settings_service()
    views = {view.platform.value: view for view in service.build_platform_views()}
    statuses: list[dict[str, Any]] = []
    for platform in ("wecom", "feishu", "dingtalk"):
        record = service.get_platform_settings(_platform_type(platform))
        view = views.get(platform)
        metadata = dict(record.metadata) if record else {}
        statuses.append(
            {
                "platform": platform,
                "enabled": bool(record.enabled) if record else False,
                "configured_keys": view.configured_keys if view else [],
                "missing_keys": view.missing_keys if view else [],
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
