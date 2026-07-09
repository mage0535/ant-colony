from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_inbound_gateway_intercepts_menu_command_only() -> None:
    from src.gateway.dispatcher import Dispatcher
    from src.gateway.inbound_service import InboundGatewayService

    service = InboundGatewayService(dispatcher=Dispatcher(), batch_processor=MagicMock())
    service.get_or_create_agent = MagicMock()

    with patch.dict(
        "os.environ",
        {"ANT_COLONY_PUBLIC_BASE_URL": "http://example.test", "ANT_COLONY_ADMIN_SESSION_SECRET": "secret"},
        clear=False,
    ):
        result = service.handle_wecom_payload(
            {
                "from_user_id": "u1",
                "msg_type": "text",
                "content": "菜单",
                "is_direct": True,
                "provider": "wecom_bot",
            }
        )

    assert result.route_kind == "personal"
    assert result.response is not None
    assert "入口" in result.response.text
    service.get_or_create_agent.assert_not_called()


def test_inbound_gateway_lets_llm_handle_fuzzy_entry_queries() -> None:
    """Now '打开知识库' goes through LLM for natural understanding, not pre-intercepted."""
    from src.gateway.dispatcher import Dispatcher
    from src.gateway.inbound_service import InboundGatewayService

    # Verify the pre-filter does NOT intercept this
    from src.gateway.entry_links import is_entry_menu_command
    assert not is_entry_menu_command("打开知识库"), "打开知识库 should NOT be menu-intercept, goes through LLM"

    # Verify the pre-filter DOES intercept obvious menu commands
    assert is_entry_menu_command("菜单"), "菜单 should still be menu-intercept for zero cost"
