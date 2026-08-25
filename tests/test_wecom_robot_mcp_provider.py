from __future__ import annotations

from pathlib import Path


def test_mcp_status_masks_apikey(monkeypatch, tmp_path: Path) -> None:
    from src.platform.wecom_robot_mcp_provider import WeComRobotMcpProvider

    monkeypatch.delenv("WECOM_ROBOT_DOC_MCP_URL", raising=False)
    monkeypatch.delenv("WECOM_ROBOT_TODO_MCP_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    provider = WeComRobotMcpProvider(
        doc_url="https://example.test/mcp/doc?apikey=abcdef1234567890",
        todo_url="",
    )

    status = provider.status()

    assert status["doc"]["configured"] is True
    assert "abcdef1234567890" not in status["doc"]["url_masked"]
    assert "abcdef" in status["doc"]["url_masked"]
    assert "7890" in status["doc"]["url_masked"]
    assert status["todo"]["configured"] is False


def test_save_mcp_urls_writes_only_env_keys(tmp_path: Path) -> None:
    from src.platform.wecom_robot_mcp_provider import save_wecom_robot_mcp_urls

    env_file = tmp_path / ".env.wecom"
    result = save_wecom_robot_mcp_urls(
        doc_url="https://example.test/doc?apikey=doc-secret",
        todo_url="https://example.test/todo?apikey=todo-secret",
        env_file=env_file,
    )

    text = env_file.read_text(encoding="utf-8")
    assert "WECOM_ROBOT_DOC_MCP_URL=" in text
    assert "WECOM_ROBOT_TODO_MCP_URL=" in text
    assert sorted(result["saved_keys"]) == ["WECOM_ROBOT_DOC_MCP_URL", "WECOM_ROBOT_TODO_MCP_URL"]


def test_sse_json_parser_reads_last_data_event() -> None:
    from src.platform.wecom_robot_mcp_provider import _parse_sse_json

    assert _parse_sse_json('event: message\ndata: {"jsonrpc":"2.0","result":{"ok":true}}\n\n') == {
        "jsonrpc": "2.0",
        "result": {"ok": True},
    }


def test_mcp_error_sanitizer_masks_apikey() -> None:
    from src.platform.wecom_robot_mcp_provider import _sanitize_error

    message = _sanitize_error(RuntimeError("failed url=https://example.test?apikey=abcdef1234567890"))

    assert "abcdef1234567890" not in message
    assert "abcdef" in message
    assert "7890" in message
