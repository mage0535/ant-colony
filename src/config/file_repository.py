from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from src.config.contracts import (
    AdminSettingsRecord,
    LLMProvider,
    LLMSettingsRecord,
    PlatformSettingsRecord,
    PlatformType,
)
from src.config.file_permissions import restrict_to_owner
from src.config.repository import InMemorySettingsRepository


class JsonFileSettingsRepository(InMemorySettingsRepository):
    """Simple JSON-backed settings repository for M1/P-1.

    This keeps the service layer stable while giving the project a persistent
    store that is easy to inspect, sync, and migrate later.
    """

    def __init__(self, file_path: str | Path) -> None:
        super().__init__()
        self.file_path = Path(file_path)
        self._load()

    def save_llm_profile(self, record: LLMSettingsRecord) -> LLMSettingsRecord:
        saved = super().save_llm_profile(record)
        self._flush()
        return saved

    def delete_llm_profile(self, profile_id: str) -> bool:
        deleted = super().delete_llm_profile(profile_id)
        if deleted:
            self._flush()
        return deleted

    def save_admin_settings(self, record: AdminSettingsRecord) -> AdminSettingsRecord:
        saved = super().save_admin_settings(record)
        self._flush()
        return saved

    def save_platform_settings(self, record: PlatformSettingsRecord) -> PlatformSettingsRecord:
        saved = super().save_platform_settings(record)
        self._flush()
        return saved

    def clear(self) -> None:
        super().clear()
        self._flush()

    def _load(self) -> None:
        if not self.file_path.exists():
            return

        payload = json.loads(self.file_path.read_text(encoding="utf-8"))

        for item in payload.get("llm_profiles", []):
            super().save_llm_profile(
                LLMSettingsRecord(
                    provider=LLMProvider(item["provider"]),
                    profile_id=item["profile_id"],
                    model_name=item["model_name"],
                    api_key=item["api_key"],
                    api_base=item.get("api_base"),
                    max_tokens=item.get("max_tokens", 4096),
                    timeout_seconds=item.get("timeout_seconds", 120),
                    enabled=item.get("enabled", True),
                    metadata=item.get("metadata", {}),
                )
            )

        admin = payload.get("admin_settings")
        if admin:
            super().save_admin_settings(
                AdminSettingsRecord(
                    admin_user_ids=admin.get("admin_user_ids", []),
                    web_default_password=admin.get("web_default_password", "admin"),
                    pause_command_enabled=admin.get("pause_command_enabled", True),
                    handoff_command_enabled=admin.get("handoff_command_enabled", True),
                    task_confirmation_required=admin.get("task_confirmation_required", True),
                    metadata=admin.get("metadata", {}),
                )
            )

        for item in payload.get("platforms", []):
            super().save_platform_settings(
                PlatformSettingsRecord(
                    platform=PlatformType(item["platform"]),
                    enabled=item.get("enabled", False),
                    settings=item.get("settings", {}),
                    metadata=item.get("metadata", {}),
                )
            )

    def _flush(self) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "llm_profiles": [self._dump_enum_dataclass(record) for record in self.list_llm_profiles()],
            "admin_settings": self._dump_enum_dataclass(self.get_admin_settings()) if self.get_admin_settings() else None,
            "platforms": [self._dump_enum_dataclass(record) for record in self.list_platform_settings()],
        }
        self.file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        restrict_to_owner(self.file_path)

    @staticmethod
    def _dump_enum_dataclass(record: object | None) -> dict | None:
        if record is None:
            return None
        payload = asdict(record)
        for key, value in list(payload.items()):
            if hasattr(value, "value"):
                payload[key] = value.value
        return payload
