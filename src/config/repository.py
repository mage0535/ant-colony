from __future__ import annotations

from dataclasses import replace

from src.config.contracts import (
    AdminSettingsRecord,
    LLMSettingsRecord,
    PlatformSettingsRecord,
    PlatformType,
)


class InMemorySettingsRepository:
    def __init__(self) -> None:
        self._llm_profiles: dict[str, LLMSettingsRecord] = {}
        self._admin_settings: AdminSettingsRecord | None = None
        self._platforms: dict[PlatformType, PlatformSettingsRecord] = {}

    def clear(self) -> None:
        self._llm_profiles.clear()
        self._admin_settings = None
        self._platforms.clear()

    def save_llm_profile(self, record: LLMSettingsRecord) -> LLMSettingsRecord:
        self._llm_profiles[record.profile_id] = replace(record)
        return replace(record)

    def get_llm_profile(self, profile_id: str) -> LLMSettingsRecord | None:
        record = self._llm_profiles.get(profile_id)
        return replace(record) if record else None

    def delete_llm_profile(self, profile_id: str) -> bool:
        return self._llm_profiles.pop(profile_id, None) is not None

    def list_llm_profiles(self) -> list[LLMSettingsRecord]:
        return [replace(record) for record in self._llm_profiles.values()]

    def save_admin_settings(self, record: AdminSettingsRecord) -> AdminSettingsRecord:
        self._admin_settings = replace(record)
        return replace(record)

    def get_admin_settings(self) -> AdminSettingsRecord | None:
        return replace(self._admin_settings) if self._admin_settings else None

    def save_platform_settings(self, record: PlatformSettingsRecord) -> PlatformSettingsRecord:
        self._platforms[record.platform] = replace(record)
        return replace(record)

    def get_platform_settings(self, platform: PlatformType) -> PlatformSettingsRecord | None:
        record = self._platforms.get(platform)
        return replace(record) if record else None

    def list_platform_settings(self) -> list[PlatformSettingsRecord]:
        return [replace(record) for record in self._platforms.values()]
