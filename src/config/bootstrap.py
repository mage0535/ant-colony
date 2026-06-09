from __future__ import annotations

from pathlib import Path

from src.config.file_repository import JsonFileSettingsRepository
from src.config.service import SettingsManagementService


DEFAULT_SETTINGS_PATH = Path("./data/runtime_settings.json")


def build_settings_service(file_path: str | Path | None = None) -> SettingsManagementService:
    """Build a persistent settings service backed by the default JSON file."""
    repository = JsonFileSettingsRepository(file_path or DEFAULT_SETTINGS_PATH)
    service = SettingsManagementService(repository)
    service.ensure_defaults()
    return service
