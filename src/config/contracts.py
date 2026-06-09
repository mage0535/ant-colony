from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class LLMProvider(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    DEEPSEEK = "deepseek"
    OPENAI_COMPATIBLE = "openai_compatible"


class PlatformType(str, Enum):
    WECOM = "wecom"
    FEISHU = "feishu"
    DINGTALK = "dingtalk"
    OPENCLAW = "openclaw"


@dataclass(slots=True)
class LLMSettingsRecord:
    provider: LLMProvider
    profile_id: str
    model_name: str
    api_key: str
    api_base: str | None = None
    max_tokens: int = 4096
    timeout_seconds: int = 120
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AdminSettingsRecord:
    admin_user_ids: list[str]
    web_default_password: str
    pause_command_enabled: bool = True
    handoff_command_enabled: bool = True
    task_confirmation_required: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PlatformSettingsRecord:
    platform: PlatformType
    enabled: bool
    settings: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RuntimeSettingsSnapshot:
    llm_profiles: list[LLMSettingsRecord] = field(default_factory=list)
    admin_settings: AdminSettingsRecord | None = None
    platforms: list[PlatformSettingsRecord] = field(default_factory=list)


@dataclass(slots=True)
class SettingsIssue:
    scope: str
    severity: str
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SettingsReadinessReport:
    ready: bool
    issues: list[SettingsIssue] = field(default_factory=list)


@dataclass(slots=True)
class LLMSettingsView:
    provider: LLMProvider
    profile_id: str
    model_name: str
    api_key_configured: bool
    api_base: str | None = None
    max_tokens: int = 4096
    timeout_seconds: int = 120
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PlatformSettingsView:
    platform: PlatformType
    enabled: bool
    configured_keys: list[str] = field(default_factory=list)
    missing_keys: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
