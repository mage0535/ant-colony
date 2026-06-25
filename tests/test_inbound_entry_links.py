from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_inbound_gateway_intercepts_knowledge_entry_command() -> None:
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
    assert "http://example.test/knowledge/user?" in result.response.text
    service.get_or_create_agent.assert_not_called()


def test_inbound_gateway_uses_forwarded_platform_for_entry_link() -> None:
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
                "from": "feishu-user",
                "text": "打开知识库",
                "platform": "feishu",
                "is_direct": True,
            }
        )

    assert result.response is not None
    assert "platform=feishu" in result.response.text
    assert "user_id=feishu-user" in result.response.text
    service.get_or_create_agent.assert_not_called()
