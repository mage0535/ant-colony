from __future__ import annotations

from src.config.bootstrap import build_settings_service
from src.engine.base import AgentEngine, AgentEngineConfig
from src.tools.builtin import register_builtin_tools
from src.tools.registry import FusionToolRegistry


def build_registry() -> FusionToolRegistry:
    registry = FusionToolRegistry()
    register_builtin_tools(registry)
    return registry


def build_engine(agent_role: str = "personal", profile_id: str | None = None) -> AgentEngine:
    svc = build_settings_service()
    snapshot = svc.build_runtime_snapshot()

    profile = None
    if profile_id:
        for p in snapshot.llm_profiles:
            if p.profile_id == profile_id and p.enabled:
                profile = p
                break
    if not profile:
        for p in snapshot.llm_profiles:
            if p.enabled and bool((p.metadata or {}).get("is_default")):
                profile = p
                break
    if not profile and profile_id:
        for p in snapshot.llm_profiles:
            if p.profile_id == profile_id and p.enabled:
                profile = p
                break
    if not profile:
        for p in snapshot.llm_profiles:
            if p.enabled:
                profile = p
                break

    config = AgentEngineConfig(
        model_name=profile.model_name if profile else "gpt-4o-mini",
        agent_role=agent_role,
        provider=profile.provider if profile else "openai",
        api_key=profile.api_key if profile else "",
        api_base=profile.api_base if profile else "",
        max_tokens=profile.max_tokens if profile else 4096,
    )
    registry = build_registry()
    return AgentEngine(config, tool_registry=registry)
