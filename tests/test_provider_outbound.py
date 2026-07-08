from __future__ import annotations

from unittest.mock import patch


def test_send_platform_text_routes_to_platform_sender() -> None:
    from src.gateway.provider_outbound import send_platform_text

    with patch("src.gateway.provider_outbound.send_text", return_value=True) as wecom_send, \
         patch("src.gateway.provider_outbound.FeishuAdapter") as feishu_cls, \
         patch("src.gateway.provider_outbound.DingTalkAdapter") as ding_cls:
        feishu_cls.return_value.send_message.return_value = True
        ding_cls.return_value.send_message.return_value = True

        assert send_platform_text("wecom", "u1", "hello") is True
        assert send_platform_text("feishu", "chat-1", "hello") is True
        assert send_platform_text("dingtalk", "chat-2", "hello") is True

    wecom_send.assert_called_once_with("u1", "hello")
    feishu_cls.return_value.send_message.assert_called_once_with("chat-1", "hello")
    ding_cls.return_value.send_message.assert_called_once_with("chat-2", "hello", title="AI 助手")


def test_send_platform_entry_payload_routes_cards_and_text() -> None:
    from src.gateway.provider_outbound import send_platform_entry_payload

    payloads = {
        "text": "可用入口",
        "feishu_card": {"header": {"title": {"content": "Ant Colony 入口"}}},
        "dingtalk_card": {"title": "Ant Colony 入口"},
    }
    with patch("src.gateway.provider_outbound.send_text", return_value=True) as wecom_send, \
         patch("src.gateway.provider_outbound.FeishuAdapter") as feishu_cls, \
         patch("src.gateway.provider_outbound.DingTalkAdapter") as ding_cls:
        feishu_cls.return_value.send_entry_card.return_value = True
        ding_cls.return_value.send_entry_card.return_value = True

        assert send_platform_entry_payload("wecom", "u1", payloads) is True
        assert send_platform_entry_payload("feishu", "chat-1", payloads) is True
        assert send_platform_entry_payload("dingtalk", "chat-2", payloads) is True

    wecom_send.assert_called_once_with("u1", "可用入口")
    feishu_cls.return_value.send_entry_card.assert_called_once_with("chat-1", payloads["feishu_card"])
    ding_cls.return_value.send_entry_card.assert_called_once_with("chat-2", payloads["dingtalk_card"])
