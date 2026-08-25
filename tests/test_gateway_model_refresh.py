from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_existing_personal_agent_refreshes_engine_when_default_model_changes(tmp_path, monkeypatch) -> None:
    from src.agents.personal_agent import PersonalAgent
    from src.config.bootstrap import DEFAULT_SETTINGS_PATH
    from src.engine.base import AgentEngine, AgentEngineConfig
    from src.gateway.inbound_service import InboundGatewayService

    settings_path = tmp_path / "runtime_settings.json"
    monkeypatch.setattr("src.config.bootstrap.DEFAULT_SETTINGS_PATH", settings_path)

    old_engine = AgentEngine(AgentEngineConfig(model_name="old-model", provider="openai_compatible", api_key="old", api_base="https://old.example/v1", agent_role="personal"))
    new_engine = AgentEngine(AgentEngineConfig(model_name="new-model", provider="openai_compatible", api_key="new", api_base="https://new.example/v1", agent_role="personal"))
    agent = PersonalAgent("u1", old_engine)
    service = InboundGatewayService(
        dispatcher=MagicMock(),
        batch_processor=MagicMock(),
        personal_agents={"u1": agent},
        engine=old_engine,
    )

    from src.platform.model_management_service import save_model_profile, set_default_model_profile

    save_model_profile({"profile_id": "new", "provider": "openai_compatible", "model_name": "new-model", "api_base": "https://new.example/v1", "api_key": "new"})
    set_default_model_profile("new")

    with patch("src.engine.factory.build_engine", return_value=new_engine) as build:
        refreshed = service.get_or_create_agent("u1")

    assert refreshed is agent
    assert refreshed.engine is new_engine
    assert service._engine is new_engine
    build.assert_called_once_with("personal")
