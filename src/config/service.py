from __future__ import annotations

from src.config.contracts import (
    AdminSettingsRecord,
    LLMSettingsRecord,
    LLMProvider,
    LLMSettingsView,
    PlatformSettingsRecord,
    PlatformType,
    PlatformSettingsView,
    RuntimeSettingsSnapshot,
    SettingsIssue,
    SettingsReadinessReport,
)
from src.config.repository import InMemorySettingsRepository
from src.config.settings import Settings


class SettingsManagementService:
    REQUIRED_PLATFORM_KEYS: dict[PlatformType, tuple[str, ...]] = {
        PlatformType.WECOM: ("corp_id", "agent_id", "secret", "callback_token", "callback_aes_key"),
        PlatformType.FEISHU: ("app_id", "app_secret"),
        PlatformType.DINGTALK: ("app_key", "app_secret", "robot_code"),
        PlatformType.OPENCLAW: ("gateway_url",),
    }

    def __init__(self, repository: InMemorySettingsRepository) -> None:
        self.repository = repository

    def save_llm_profile(self, record: LLMSettingsRecord) -> LLMSettingsRecord:
        return self.repository.save_llm_profile(record)

    def upsert_llm_profile(
        self,
        *,
        profile_id: str,
        provider: LLMProvider,
        model_name: str,
        api_key: str | None = None,
        api_base: str | None = None,
        max_tokens: int | None = None,
        timeout_seconds: int | None = None,
        enabled: bool | None = None,
        metadata: dict[str, object] | None = None,
    ) -> LLMSettingsRecord:
        existing = self.repository.get_llm_profile(profile_id)
        if existing is None:
            record = LLMSettingsRecord(
                provider=provider,
                profile_id=profile_id,
                model_name=model_name,
                api_key=api_key or "",
                api_base=api_base,
                max_tokens=max_tokens or 4096,
                timeout_seconds=timeout_seconds or 120,
                enabled=True if enabled is None else enabled,
                metadata=dict(metadata or {}),
            )
        else:
            record = LLMSettingsRecord(
                provider=provider,
                profile_id=profile_id,
                model_name=model_name,
                api_key=existing.api_key if api_key is None else api_key,
                api_base=existing.api_base if api_base is None else api_base,
                max_tokens=existing.max_tokens if max_tokens is None else max_tokens,
                timeout_seconds=existing.timeout_seconds if timeout_seconds is None else timeout_seconds,
                enabled=existing.enabled if enabled is None else enabled,
                metadata={**existing.metadata, **dict(metadata or {})},
            )
        return self.repository.save_llm_profile(record)

    def get_llm_profile(self, profile_id: str) -> LLMSettingsRecord | None:
        return self.repository.get_llm_profile(profile_id)

    def list_llm_profiles(self, *, enabled_only: bool = False) -> list[LLMSettingsRecord]:
        profiles = self.repository.list_llm_profiles()
        if enabled_only:
            return [profile for profile in profiles if profile.enabled]
        return profiles

    def save_admin_settings(self, record: AdminSettingsRecord) -> AdminSettingsRecord:
        return self.repository.save_admin_settings(record)

    def upsert_admin_settings(
        self,
        *,
        admin_user_ids: list[str] | None = None,
        web_default_password: str | None = None,
        pause_command_enabled: bool | None = None,
        handoff_command_enabled: bool | None = None,
        task_confirmation_required: bool | None = None,
        metadata: dict[str, object] | None = None,
    ) -> AdminSettingsRecord:
        existing = self.repository.get_admin_settings() or self.default_admin_settings()
        record = AdminSettingsRecord(
            admin_user_ids=existing.admin_user_ids if admin_user_ids is None else admin_user_ids,
            web_default_password=existing.web_default_password if web_default_password is None else web_default_password,
            pause_command_enabled=existing.pause_command_enabled if pause_command_enabled is None else pause_command_enabled,
            handoff_command_enabled=existing.handoff_command_enabled if handoff_command_enabled is None else handoff_command_enabled,
            task_confirmation_required=(
                existing.task_confirmation_required if task_confirmation_required is None else task_confirmation_required
            ),
            metadata={**existing.metadata, **dict(metadata or {})},
        )
        return self.repository.save_admin_settings(record)

    def get_admin_settings(self) -> AdminSettingsRecord | None:
        return self.repository.get_admin_settings()

    def save_platform_settings(self, record: PlatformSettingsRecord) -> PlatformSettingsRecord:
        return self.repository.save_platform_settings(record)

    def upsert_platform_settings(
        self,
        *,
        platform: PlatformType,
        enabled: bool | None = None,
        settings: dict[str, str] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> PlatformSettingsRecord:
        existing = self.repository.get_platform_settings(platform) or PlatformSettingsRecord(platform=platform, enabled=False)
        record = PlatformSettingsRecord(
            platform=platform,
            enabled=existing.enabled if enabled is None else enabled,
            settings={**existing.settings, **dict(settings or {})},
            metadata={**existing.metadata, **dict(metadata or {})},
        )
        return self.repository.save_platform_settings(record)

    def get_platform_settings(self, platform: PlatformType) -> PlatformSettingsRecord | None:
        return self.repository.get_platform_settings(platform)

    def list_platform_settings(self, *, enabled_only: bool = False) -> list[PlatformSettingsRecord]:
        platforms = self.repository.list_platform_settings()
        if enabled_only:
            return [platform for platform in platforms if platform.enabled]
        return platforms

    def build_runtime_snapshot(self) -> RuntimeSettingsSnapshot:
        return RuntimeSettingsSnapshot(
            llm_profiles=self.repository.list_llm_profiles(),
            admin_settings=self.repository.get_admin_settings(),
            platforms=self.repository.list_platform_settings(),
        )

    def build_llm_views(self) -> list[LLMSettingsView]:
        return [
            LLMSettingsView(
                provider=profile.provider,
                profile_id=profile.profile_id,
                model_name=profile.model_name,
                api_key_configured=bool(profile.api_key),
                api_base=profile.api_base,
                max_tokens=profile.max_tokens,
                timeout_seconds=profile.timeout_seconds,
                enabled=profile.enabled,
                metadata=profile.metadata,
            )
            for profile in self.repository.list_llm_profiles()
        ]

    def build_platform_views(self) -> list[PlatformSettingsView]:
        views: list[PlatformSettingsView] = []
        for platform in self.repository.list_platform_settings():
            required_keys = self.REQUIRED_PLATFORM_KEYS.get(platform.platform, ())
            configured_keys = [key for key, value in platform.settings.items() if value]
            missing_keys = [key for key in required_keys if not platform.settings.get(key)]
            views.append(
                PlatformSettingsView(
                    platform=platform.platform,
                    enabled=platform.enabled,
                    configured_keys=sorted(configured_keys),
                    missing_keys=missing_keys,
                    metadata=platform.metadata,
                )
            )
        return views

    def ensure_defaults(self) -> RuntimeSettingsSnapshot:
        if self.repository.get_admin_settings() is None:
            self.repository.save_admin_settings(self.default_admin_settings())

        for record in self.default_platform_records():
            if self.repository.get_platform_settings(record.platform) is None:
                self.repository.save_platform_settings(record)

        return self.build_runtime_snapshot()

    def reset(self) -> RuntimeSettingsSnapshot:
        self.repository.clear()
        return self.ensure_defaults()

    def audit_readiness(self) -> SettingsReadinessReport:
        issues: list[SettingsIssue] = []
        snapshot = self.build_runtime_snapshot()

        enabled_llm_profiles = [profile for profile in snapshot.llm_profiles if profile.enabled]
        if not enabled_llm_profiles:
            issues.append(
                SettingsIssue(
                    scope="llm",
                    severity="error",
                    message="No enabled LLM profile configured.",
                )
            )
        else:
            for profile in enabled_llm_profiles:
                if not profile.api_key:
                    issues.append(
                        SettingsIssue(
                            scope="llm",
                            severity="error",
                            message=f"LLM profile '{profile.profile_id}' has no API key.",
                            metadata={"profile_id": profile.profile_id},
                        )
                    )

        admin_settings = snapshot.admin_settings
        if admin_settings is None:
            issues.append(
                SettingsIssue(
                    scope="admin",
                    severity="error",
                    message="Admin settings are missing.",
                )
            )
        else:
            if not admin_settings.admin_user_ids:
                issues.append(
                    SettingsIssue(
                        scope="admin",
                        severity="error",
                        message="No admin user IDs configured.",
                    )
                )
            if not admin_settings.web_default_password or admin_settings.web_default_password == "admin":
                issues.append(
                    SettingsIssue(
                        scope="admin",
                        severity="warning",
                        message="Web default password is missing or still uses the default value.",
                    )
                )

        for platform in snapshot.platforms:
            if not platform.enabled:
                continue
            required_keys = self.REQUIRED_PLATFORM_KEYS.get(platform.platform, ())
            missing_keys = [key for key in required_keys if not platform.settings.get(key)]
            if missing_keys:
                issues.append(
                    SettingsIssue(
                        scope=f"platform:{platform.platform.value}",
                        severity="error",
                        message=f"Platform '{platform.platform.value}' is enabled but missing required keys.",
                        metadata={"missing_keys": missing_keys},
                    )
                )

        return SettingsReadinessReport(
            ready=not any(issue.severity == "error" for issue in issues),
            issues=issues,
        )

    def build_engine_config(self, profile_id: str, agent_role: str):
        from src.engine import AgentEngineConfig

        profile = self.repository.get_llm_profile(profile_id)
        if profile is None:
            raise KeyError(f"Unknown LLM profile: {profile_id}")
        return AgentEngineConfig(
            model_name=profile.model_name,
            agent_role=agent_role,
            metadata={
                "provider": profile.provider.value,
                "profile_id": profile.profile_id,
                "api_base": profile.api_base,
                "max_tokens": profile.max_tokens,
                "timeout_seconds": profile.timeout_seconds,
            },
        )

    def build_settings_from_snapshot(self) -> Settings:
        snapshot = self.build_runtime_snapshot()
        return Settings.from_management_snapshot(snapshot)

    @staticmethod
    def default_admin_settings() -> AdminSettingsRecord:
        return AdminSettingsRecord(
            admin_user_ids=[],
            web_default_password="admin",
            pause_command_enabled=True,
            handoff_command_enabled=True,
            task_confirmation_required=True,
        )

    @staticmethod
    def default_platform_records() -> list[PlatformSettingsRecord]:
        return [
            PlatformSettingsRecord(platform=PlatformType.WECOM, enabled=False),
            PlatformSettingsRecord(platform=PlatformType.FEISHU, enabled=False),
            PlatformSettingsRecord(platform=PlatformType.DINGTALK, enabled=False),
            PlatformSettingsRecord(platform=PlatformType.OPENCLAW, enabled=False),
        ]

    @staticmethod
    def make_llm_profile(
        *,
        provider: LLMProvider,
        profile_id: str,
        model_name: str,
        api_key: str,
        api_base: str | None = None,
        enabled: bool = True,
    ) -> LLMSettingsRecord:
        return LLMSettingsRecord(
            provider=provider,
            profile_id=profile_id,
            model_name=model_name,
            api_key=api_key,
            api_base=api_base,
            enabled=enabled,
        )
