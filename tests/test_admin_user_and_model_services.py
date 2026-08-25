from __future__ import annotations

import urllib.error
from io import BytesIO
from unittest.mock import patch


def test_user_management_merges_org_users_bot_status_and_usage(tmp_path, monkeypatch) -> None:
    from src.store.database import Database

    db_path = tmp_path / "ant-colony.db"
    monkeypatch.setenv("ANT_COLONY_DB_PATH", str(db_path))
    Database._instances.clear()
    graph = __import__("src.platform.org_graph", fromlist=["OrgGraphService"]).OrgGraphService(str(db_path))
    graph.upsert_department("wecom", "1", "总经办", "")
    graph.upsert_user("wecom", "u1", "张三")
    graph.replace_user_memberships("wecom", "u1", [("1", False, True)])

    from src.platform.employee_bot_service import activate_employee_bot
    from src.platform.assistant_profile_service import save_assistant_profile
    from src.platform.user_management_service import list_admin_user_details

    with patch("src.platform.employee_bot_service._notify_employee", return_value="sent"):
        activate_employee_bot(platform="wecom", user_id="u1", display_name="企业 AI 助手", notify=True)
    save_assistant_profile(platform="wecom", user_id="u1", assistant_name="小智", user_call_name="张总", role_id="document_specialist")

    result = list_admin_user_details("wecom", sync=False)

    assert result["users"][0]["user_id"] == "u1"
    assert result["users"][0]["bot_status"] == "active"
    assert result["users"][0]["assistant_name"] == "小智"
    assert result["users"][0]["assistant_user_call_name"] == "张总"
    assert result["users"][0]["assistant_role_id"] == "document_specialist"
    assert result["users"][0]["is_admin"] is True


def test_model_discovery_without_key_returns_actionable_message() -> None:
    from src.platform.model_management_service import discover_models

    result = discover_models({"provider": "openai", "api_key": ""})

    assert result["ok"] is False
    assert "API Key" in result["message"]


def test_model_discovery_403_returns_manual_entry_guidance() -> None:
    from src.platform.model_management_service import discover_models

    error = urllib.error.HTTPError(
        "https://example.com/v1/models",
        403,
        "Forbidden",
        {},
        BytesIO(b'{"error":"model listing forbidden"}'),
    )

    with patch("urllib.request.urlopen", side_effect=error):
        result = discover_models({
            "provider": "openai_compatible",
            "sdk_format": "openai",
            "api_base": "https://example.com/v1",
            "api_key": "sk-test",
        })

    assert result["ok"] is False
    assert result["manual_entry_supported"] is True
    assert result["status_code"] == 403
    assert "手工填写" in result["message"]
    assert "模型 ID" in result["message"]
    assert "HTTP 403" in result["message"]
    assert "sk-test" not in result["message"]


def test_model_discovery_prefers_sdk_format_for_anthropic_compatible_provider() -> None:
    from src.platform.model_management_service import discover_models

    with patch("src.platform.model_management_service._discover_anthropic_models", return_value={"ok": True, "models": []}) as anthropic, \
         patch("src.platform.model_management_service._discover_openai_models") as openai:
        discover_models({
            "provider": "openai_compatible",
            "sdk_format": "anthropic",
            "api_base": "https://anthropic-compatible.example/v1",
            "api_key": "sk-test",
        })

    anthropic.assert_called_once()
    openai.assert_not_called()


def test_model_discovery_accepts_full_opencode_models_endpoint_without_prefixing_ids() -> None:
    from src.platform.model_management_service import discover_models

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"data":[{"id":"gpt-5.5","name":"GPT 5.5"},{"id":"opencode/claude-sonnet","name":"Claude"}]}'

    requested_urls: list[str] = []
    requested_headers: list[dict[str, str]] = []

    def fake_urlopen(req, timeout=20):
        requested_urls.append(req.full_url)
        requested_headers.append(dict(req.header_items()))
        return FakeResponse()

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = discover_models({
            "provider": "openai_compatible",
            "sdk_format": "openai",
            "api_base": "https://opencode.ai/zen/v1/models",
            "api_key": "sk-test",
        })

    assert requested_urls == ["https://opencode.ai/zen/v1/models"]
    assert requested_headers[0]["User-agent"] == "Ant-Colony-AI-Assistant/1.0"
    assert requested_headers[0]["Accept"] == "application/json, text/plain, */*"
    assert result["ok"] is True
    assert result["models"][0]["id"] == "gpt-5.5"
    assert result["models"][1]["id"] == "opencode/claude-sonnet"


def test_opencode_config_model_id_is_normalized_for_zen_api() -> None:
    from src.platform.model_management_service import normalize_model_name_for_api

    assert normalize_model_name_for_api("opencode/deepseek-v4-flash-free", "https://opencode.ai/zen/v1") == "deepseek-v4-flash-free"
    assert normalize_model_name_for_api("opencode/deepseek-v4-flash-free", "https://example.com/v1") == "opencode/deepseek-v4-flash-free"


def test_set_default_model_profile_marks_only_one_default(tmp_path, monkeypatch) -> None:
    from src.platform.model_management_service import list_model_profiles, save_model_profile, set_default_model_profile

    settings_path = tmp_path / "runtime_settings.json"
    monkeypatch.setattr("src.config.bootstrap.DEFAULT_SETTINGS_PATH", settings_path)

    save_model_profile({"profile_id": "a", "provider": "openai_compatible", "model_name": "opencode/gpt-5.5", "api_key": "k1"})
    save_model_profile({"profile_id": "b", "provider": "openai_compatible", "model_name": "opencode/gpt-5-mini", "api_key": "k2"})
    result = set_default_model_profile("b")

    profiles = {item["profile_id"]: item for item in list_model_profiles()["profiles"]}
    assert result["profile_id"] == "b"
    assert profiles["b"]["is_default"] is True
    assert profiles["a"]["is_default"] is False


def test_delete_model_profile_removes_profile_and_reassigns_default(tmp_path, monkeypatch) -> None:
    from src.platform.model_management_service import delete_model_profile, list_model_profiles, save_model_profile, set_default_model_profile

    settings_path = tmp_path / "runtime_settings.json"
    monkeypatch.setattr("src.config.bootstrap.DEFAULT_SETTINGS_PATH", settings_path)

    save_model_profile({"profile_id": "a", "provider": "openai_compatible", "model_name": "opencode/gpt-5.5", "api_key": "k1"})
    save_model_profile({"profile_id": "b", "provider": "openai_compatible", "model_name": "opencode/gpt-5-mini", "api_key": "k2"})
    set_default_model_profile("b")

    result = delete_model_profile("b")
    profiles = {item["profile_id"]: item for item in list_model_profiles()["profiles"]}

    assert result == {"ok": True, "profile_id": "b", "deleted": True}
    assert "b" not in profiles
    assert profiles["a"]["is_default"] is True


def test_build_engine_prefers_default_profile(tmp_path, monkeypatch) -> None:
    from src.engine.factory import build_engine
    from src.platform.model_management_service import save_model_profile, set_default_model_profile

    settings_path = tmp_path / "runtime_settings.json"
    monkeypatch.setattr("src.config.bootstrap.DEFAULT_SETTINGS_PATH", settings_path)

    save_model_profile({"profile_id": "a", "provider": "openai_compatible", "model_name": "opencode/gpt-5.5", "api_key": "k1"})
    save_model_profile({"profile_id": "b", "provider": "anthropic", "model_name": "claude-sonnet-4-20250514", "api_key": "k2"})
    set_default_model_profile("b")

    engine = build_engine("personal")

    assert engine.config.model_name == "claude-sonnet-4-20250514"
    assert engine.config.provider == "anthropic"


def test_model_profile_test_invokes_selected_profile(tmp_path, monkeypatch) -> None:
    from src.platform.model_management_service import save_model_profile, test_model_profile

    settings_path = tmp_path / "runtime_settings.json"
    monkeypatch.setattr("src.config.bootstrap.DEFAULT_SETTINGS_PATH", settings_path)

    save_model_profile({
        "profile_id": "test-model",
        "provider": "openai_compatible",
        "model_name": "x-preview-f-free",
        "api_base": "https://opencode.ai/zen/v1/",
        "api_key": "sk-test",
    })

    class FakeResponse:
        text = "正常"
        metadata = {"model": "x-preview-f-free", "provider": "openai_compatible"}

    class FakeEngine:
        def __init__(self):
            self.config = type("Config", (), {
                "model_name": "x-preview-f-free",
                "provider": "openai_compatible",
                "api_base": "https://opencode.ai/zen/v1/",
            })()

        def process_text(self, text, context):
            assert "只回复" in text
            return FakeResponse()

    with patch("src.engine.factory.build_engine", return_value=FakeEngine()) as build:
        result = test_model_profile("test-model")

    assert result["ok"] is True
    assert result["profile_id"] == "test-model"
    assert result["model_name"] == "x-preview-f-free"
    assert result["response"] == "正常"
    build.assert_called_once_with(agent_role="personal", profile_id="test-model")
