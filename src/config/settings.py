from __future__ import annotations

import os
from dataclasses import dataclass

from src.config.contracts import LLMProvider, PlatformType, RuntimeSettingsSnapshot


@dataclass(slots=True)
class Settings:
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    deepseek_api_key: str | None = None
    wecom_corp_id: str | None = None
    wecom_agent_id: str | None = None
    wecom_secret: str | None = None
    wecom_callback_token: str | None = None
    wecom_callback_aes_key: str | None = None
    feishu_app_id: str | None = None
    feishu_app_secret: str | None = None
    dingtalk_app_key: str | None = None
    dingtalk_app_secret: str | None = None
    openclaw_gateway_url: str | None = None
    admin_user_ids: tuple[str, ...] = ()
    web_default_password: str | None = None
    database_url: str | None = None
    gbrain_url: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY"),
            wecom_corp_id=os.getenv("WECOM_CORP_ID"),
            wecom_agent_id=os.getenv("WECOM_AGENT_ID"),
            wecom_secret=os.getenv("WECOM_SECRET"),
            wecom_callback_token=os.getenv("WECOM_CALLBACK_TOKEN"),
            wecom_callback_aes_key=os.getenv("WECOM_CALLBACK_AES_KEY"),
            feishu_app_id=os.getenv("FEISHU_APP_ID"),
            feishu_app_secret=os.getenv("FEISHU_APP_SECRET"),
            dingtalk_app_key=os.getenv("DINGTALK_APP_KEY"),
            dingtalk_app_secret=os.getenv("DINGTALK_APP_SECRET"),
            openclaw_gateway_url=os.getenv("OPENCLAW_GATEWAY_URL"),
            admin_user_ids=tuple(filter(None, os.getenv("CONTACTS_ADMIN_USER_IDS", "").split(","))),
            web_default_password=os.getenv("WEB_DEFAULT_PASSWORD"),
            database_url=os.getenv("DATABASE_URL"),
            gbrain_url=os.getenv("GBRAIN_URL"),
        )

    @classmethod
    def from_management_snapshot(cls, snapshot: RuntimeSettingsSnapshot) -> "Settings":
        fields: dict[str, str | tuple[str, ...] | None] = {
            "openai_api_key": None,
            "anthropic_api_key": None,
            "deepseek_api_key": None,
            "wecom_corp_id": None,
            "wecom_agent_id": None,
            "wecom_secret": None,
            "wecom_callback_token": None,
            "wecom_callback_aes_key": None,
            "feishu_app_id": None,
            "feishu_app_secret": None,
            "dingtalk_app_key": None,
            "dingtalk_app_secret": None,
            "openclaw_gateway_url": None,
            "admin_user_ids": (),
            "web_default_password": None,
            "database_url": None,
            "gbrain_url": None,
        }

        for profile in snapshot.llm_profiles:
            if not profile.enabled:
                continue
            if profile.provider == LLMProvider.OPENAI:
                fields["openai_api_key"] = profile.api_key
            elif profile.provider == LLMProvider.ANTHROPIC:
                fields["anthropic_api_key"] = profile.api_key
            elif profile.provider == LLMProvider.DEEPSEEK:
                fields["deepseek_api_key"] = profile.api_key

        if snapshot.admin_settings is not None:
            fields["admin_user_ids"] = tuple(snapshot.admin_settings.admin_user_ids)
            fields["web_default_password"] = snapshot.admin_settings.web_default_password

        for platform in snapshot.platforms:
            if not platform.enabled:
                continue
            if platform.platform == PlatformType.WECOM:
                fields["wecom_corp_id"] = platform.settings.get("corp_id")
                fields["wecom_agent_id"] = platform.settings.get("agent_id")
                fields["wecom_secret"] = platform.settings.get("secret")
                fields["wecom_callback_token"] = platform.settings.get("callback_token")
                fields["wecom_callback_aes_key"] = platform.settings.get("callback_aes_key")
            elif platform.platform == PlatformType.FEISHU:
                fields["feishu_app_id"] = platform.settings.get("app_id")
                fields["feishu_app_secret"] = platform.settings.get("app_secret")
            elif platform.platform == PlatformType.DINGTALK:
                fields["dingtalk_app_key"] = platform.settings.get("app_key")
                fields["dingtalk_app_secret"] = platform.settings.get("app_secret")
            elif platform.platform == PlatformType.OPENCLAW:
                fields["openclaw_gateway_url"] = platform.settings.get("gateway_url")

        return cls(**fields)
