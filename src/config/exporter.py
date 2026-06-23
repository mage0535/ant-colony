from __future__ import annotations

from pathlib import Path

from src.config.contracts import LLMProvider, PlatformType, RuntimeSettingsSnapshot
from src.config.file_permissions import restrict_to_owner


def export_openvort_env(snapshot: RuntimeSettingsSnapshot) -> dict[str, str]:
    env: dict[str, str] = {}

    for profile in snapshot.llm_profiles:
        if not profile.enabled:
            continue
        if profile.provider == LLMProvider.OPENAI:
            env["OPENVORT_OPENAI_API_KEY"] = profile.api_key
        elif profile.provider == LLMProvider.ANTHROPIC:
            env["OPENVORT_LLM_PROVIDER"] = "anthropic"
            env["OPENVORT_LLM_API_KEY"] = profile.api_key
            if profile.api_base:
                env["OPENVORT_LLM_API_BASE"] = profile.api_base
            env["OPENVORT_LLM_MODEL"] = profile.model_name
        elif profile.provider == LLMProvider.DEEPSEEK:
            env["OPENVORT_DEEPSEEK_API_KEY"] = profile.api_key
        elif profile.provider == LLMProvider.OPENAI_COMPATIBLE:
            env["OPENVORT_LLM_PROVIDER"] = "openai_compatible"
            env["OPENVORT_LLM_API_KEY"] = profile.api_key
            if profile.api_base:
                env["OPENVORT_LLM_API_BASE"] = profile.api_base
            env["OPENVORT_LLM_MODEL"] = profile.model_name

    if snapshot.admin_settings is not None:
        env["OPENVORT_CONTACTS_ADMIN_USER_IDS"] = ",".join(snapshot.admin_settings.admin_user_ids)
        env["OPENVORT_WEB_DEFAULT_PASSWORD"] = snapshot.admin_settings.web_default_password

    for platform in snapshot.platforms:
        if not platform.enabled:
            continue
        if platform.platform == PlatformType.WECOM:
            _copy(platform.settings, env, {
                "corp_id": "OPENVORT_WECOM_CORP_ID",
                "agent_id": "OPENVORT_WECOM_AGENT_ID",
                "secret": "OPENVORT_WECOM_APP_SECRET",
                "callback_token": "OPENVORT_WECOM_CALLBACK_TOKEN",
                "callback_aes_key": "OPENVORT_WECOM_CALLBACK_AES_KEY",
            })
        elif platform.platform == PlatformType.FEISHU:
            _copy(platform.settings, env, {
                "app_id": "OPENVORT_FEISHU_APP_ID",
                "app_secret": "OPENVORT_FEISHU_APP_SECRET",
            })
        elif platform.platform == PlatformType.DINGTALK:
            _copy(platform.settings, env, {
                "app_key": "OPENVORT_DINGTALK_APP_KEY",
                "app_secret": "OPENVORT_DINGTALK_APP_SECRET",
                "robot_code": "OPENVORT_DINGTALK_ROBOT_CODE",
            })
        elif platform.platform == PlatformType.OPENCLAW:
            _copy(platform.settings, env, {
                "gateway_url": "OPENVORT_OPENCLAW_GATEWAY_URL",
            })

    return {key: value for key, value in env.items() if value}


def write_openvort_env_file(snapshot: RuntimeSettingsSnapshot, output_path: str | Path) -> Path:
    path = Path(output_path)
    env_map = export_openvort_env(snapshot)
    lines = [f"{key}={value}" for key, value in sorted(env_map.items())]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    restrict_to_owner(path)
    return path


def apply_openvort_env_overlay(snapshot: RuntimeSettingsSnapshot, target_path: str | Path) -> Path:
    path = Path(target_path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        restrict_to_owner(path)

    env_map = export_openvort_env(snapshot)
    target_lines = path.read_text(encoding="utf-8").splitlines()

    written: set[str] = set()
    new_lines: list[str] = []
    for line in target_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            new_lines.append(line)
            continue
        key, _value = line.split("=", 1)
        if key in env_map:
            new_lines.append(f"{key}={env_map[key]}")
            written.add(key)
        else:
            new_lines.append(line)

    for key, value in env_map.items():
        if key not in written:
            new_lines.append(f"{key}={value}")

    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    restrict_to_owner(path)
    return path


def _copy(source: dict[str, str], target: dict[str, str], mapping: dict[str, str]) -> None:
    for source_key, target_key in mapping.items():
        value = source.get(source_key)
        if value:
            target[target_key] = value
