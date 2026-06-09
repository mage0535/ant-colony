from __future__ import annotations

from pathlib import Path

from src.config.contracts import LLMProvider, PlatformType
from src.config.service import SettingsManagementService
from src.config.settings import Settings


def load_env_file_values(path: str | Path) -> dict[str, str]:
    env_path = Path(path)
    values: dict[str, str] = {}
    if not env_path.exists():
        return values

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key] = value
    return values


def seed_from_openvort_env_file(service: SettingsManagementService, env_path: str | Path) -> None:
    values = load_env_file_values(env_path)
    _seed_from_values(service, values)


def seed_from_settings(service: SettingsManagementService, settings: Settings) -> None:
    if settings.openai_api_key:
        service.upsert_llm_profile(
            profile_id="default-openai",
            provider=LLMProvider.OPENAI,
            model_name="gpt-5",
            api_key=settings.openai_api_key,
        )
    if settings.anthropic_api_key:
        service.upsert_llm_profile(
            profile_id="default-anthropic",
            provider=LLMProvider.ANTHROPIC,
            model_name="claude-sonnet-4",
            api_key=settings.anthropic_api_key,
        )
    if settings.deepseek_api_key:
        service.upsert_llm_profile(
            profile_id="default-deepseek",
            provider=LLMProvider.DEEPSEEK,
            model_name="deepseek-chat",
            api_key=settings.deepseek_api_key,
        )

    service.ensure_defaults()

    if settings.wecom_corp_id or settings.wecom_agent_id or settings.wecom_secret:
        service.upsert_platform_settings(
            platform=PlatformType.WECOM,
            enabled=True,
            settings={
                "corp_id": settings.wecom_corp_id or "",
                "agent_id": settings.wecom_agent_id or "",
                "secret": settings.wecom_secret or "",
                "callback_token": settings.wecom_callback_token or "",
                "callback_aes_key": settings.wecom_callback_aes_key or "",
            },
        )
    if settings.feishu_app_id or settings.feishu_app_secret:
        service.upsert_platform_settings(
            platform=PlatformType.FEISHU,
            enabled=True,
            settings={
                "app_id": settings.feishu_app_id or "",
                "app_secret": settings.feishu_app_secret or "",
            },
        )
    if settings.dingtalk_app_key or settings.dingtalk_app_secret:
        service.upsert_platform_settings(
            platform=PlatformType.DINGTALK,
            enabled=True,
            settings={
                "app_key": settings.dingtalk_app_key or "",
                "app_secret": settings.dingtalk_app_secret or "",
            },
        )
    if settings.openclaw_gateway_url:
        service.upsert_platform_settings(
            platform=PlatformType.OPENCLAW,
            enabled=True,
            settings={"gateway_url": settings.openclaw_gateway_url},
        )

    if settings.admin_user_ids or settings.web_default_password:
        service.upsert_admin_settings(
            admin_user_ids=list(settings.admin_user_ids),
            web_default_password=settings.web_default_password or "admin",
        )


def _seed_from_values(service: SettingsManagementService, values: dict[str, str]) -> None:
    service.ensure_defaults()

    provider = values.get("OPENVORT_LLM_PROVIDER")
    api_key = values.get("OPENVORT_LLM_API_KEY", "")
    model = values.get("OPENVORT_LLM_MODEL", "")
    api_base = values.get("OPENVORT_LLM_API_BASE")
    if _is_meaningful_value(provider) and _is_meaningful_value(model):
        service.upsert_llm_profile(
            profile_id="default-openvort",
            provider=LLMProvider(provider),
            model_name=model,
            api_key=api_key if _is_meaningful_value(api_key) else "",
            api_base=api_base if _is_meaningful_value(api_base) else None,
            enabled=True,
        )

    admin_ids = values.get("OPENVORT_CONTACTS_ADMIN_USER_IDS", "")
    web_password = values.get("OPENVORT_WEB_DEFAULT_PASSWORD")
    parsed_admin_ids = [item for item in admin_ids.split(",") if _is_meaningful_value(item)]
    if parsed_admin_ids or _is_meaningful_value(web_password):
        service.upsert_admin_settings(
            admin_user_ids=parsed_admin_ids,
            web_default_password=web_password if _is_meaningful_value(web_password) else "admin",
        )

    wecom_settings = {
        "corp_id": values.get("OPENVORT_WECOM_CORP_ID", ""),
        "agent_id": values.get("OPENVORT_WECOM_AGENT_ID", ""),
        "secret": values.get("OPENVORT_WECOM_APP_SECRET", ""),
        "callback_token": values.get("OPENVORT_WECOM_CALLBACK_TOKEN", ""),
        "callback_aes_key": values.get("OPENVORT_WECOM_CALLBACK_AES_KEY", ""),
    }
    filtered_wecom = {key: value for key, value in wecom_settings.items() if _is_meaningful_value(value)}
    if filtered_wecom:
        service.upsert_platform_settings(platform=PlatformType.WECOM, enabled=True, settings=filtered_wecom)

    feishu_settings = {
        "app_id": values.get("OPENVORT_FEISHU_APP_ID", ""),
        "app_secret": values.get("OPENVORT_FEISHU_APP_SECRET", ""),
    }
    filtered_feishu = {key: value for key, value in feishu_settings.items() if _is_meaningful_value(value)}
    if filtered_feishu:
        service.upsert_platform_settings(platform=PlatformType.FEISHU, enabled=True, settings=filtered_feishu)

    dingtalk_settings = {
        "app_key": values.get("OPENVORT_DINGTALK_APP_KEY", ""),
        "app_secret": values.get("OPENVORT_DINGTALK_APP_SECRET", ""),
        "robot_code": values.get("OPENVORT_DINGTALK_ROBOT_CODE", ""),
    }
    filtered_dingtalk = {key: value for key, value in dingtalk_settings.items() if _is_meaningful_value(value)}
    if filtered_dingtalk:
        service.upsert_platform_settings(platform=PlatformType.DINGTALK, enabled=True, settings=filtered_dingtalk)

    openclaw_settings = {
        "gateway_url": values.get("OPENVORT_OPENCLAW_GATEWAY_URL", ""),
    }
    filtered_openclaw = {key: value for key, value in openclaw_settings.items() if _is_meaningful_value(value)}
    if filtered_openclaw:
        service.upsert_platform_settings(platform=PlatformType.OPENCLAW, enabled=True, settings=filtered_openclaw)


def _is_meaningful_value(value: str | None) -> bool:
    if value is None:
        return False

    normalized = value.strip().lower()
    if not normalized:
        return False

    placeholder_prefixes = ("replace-with-", "your-", "example-")
    if any(normalized.startswith(prefix) for prefix in placeholder_prefixes):
        return False

    return normalized not in {"admin", "changeme", "todo", "tbd"}
