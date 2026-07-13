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


def test_inbound_gateway_intercepts_admin_console_command_without_llm() -> None:
    from src.gateway.dispatcher import Dispatcher
    from src.gateway.inbound_service import InboundGatewayService

    service = InboundGatewayService(dispatcher=Dispatcher(), batch_processor=MagicMock())
    service.get_or_create_agent = MagicMock()

    with patch.dict(
        "os.environ",
        {"ANT_COLONY_PUBLIC_BASE_URL": "http://example.test", "ANT_COLONY_ADMIN_SESSION_SECRET": "secret"},
        clear=False,
    ), patch("src.web.admin_auth.is_platform_admin", return_value=True):
        result = service.handle_wecom_payload(
            {
                "from_user_id": "u-admin",
                "msg_type": "text",
                "content": "管理员控制台",
                "is_direct": True,
                "provider": "wecom_bot",
            }
        )

    assert result.route_kind == "personal"
    assert result.response is not None
    assert "管理员控制台入口" in result.response.text
    assert "platform=wecom" in result.response.text
    service.get_or_create_agent.assert_not_called()


def test_inbound_gateway_intercepts_knowledge_command_without_llm() -> None:
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
                "content": "打开知识库",
                "is_direct": True,
                "provider": "wecom_bot",
            }
        )

    assert result.route_kind == "personal"
    assert result.response is not None
    assert "知识库管理入口" in result.response.text
    assert "platform=wecom" in result.response.text
    service.get_or_create_agent.assert_not_called()
