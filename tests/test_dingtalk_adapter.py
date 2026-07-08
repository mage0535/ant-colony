from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch


class TestDingTalkAdapter(unittest.TestCase):
    def test_handle_event_ignores_group_message_without_mentions(self) -> None:
        from src.gateway.adapter_dingtalk import DingTalkAdapter

        adapter = DingTalkAdapter()
        adapter._forward_to_gateway = MagicMock(return_value="")  # type: ignore[method-assign]

        result = adapter._handle_event(
            {
                "conversationType": "group",
                "conversationId": "chat-1",
                "senderStaffId": "u1",
                "msgtype": "text",
                "text": {"content": "hello"},
                "msgId": "m1",
                "atUsers": [],
            },
            "{}",
        )

        self.assertIsNone(result)
        adapter._forward_to_gateway.assert_not_called()

    def test_handle_event_accepts_url_verify(self) -> None:
        from src.gateway.adapter_dingtalk import DingTalkAdapter

        adapter = DingTalkAdapter()

        result = adapter._handle_event({"msgtype": "url_verify"}, "{}")

        self.assertEqual(result, {"msg": "ok"})

    def test_send_message_uses_expected_payload(self) -> None:
        from src.gateway.adapter_dingtalk import DingTalkAdapter

        adapter = DingTalkAdapter()

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps({"errcode": 0, "errmsg": "ok"}).encode("utf-8")

        seen = {}

        def fake_urlopen(req, timeout=10):
            seen["url"] = req.full_url
            seen["payload"] = req.data
            return Response()

        with (
            patch.object(adapter, "_ensure_token", return_value="token-1"),
            patch("src.gateway.adapter_dingtalk.urllib.request.urlopen", side_effect=fake_urlopen),
        ):
            ok = adapter.send_message("chat-1", "hello world")

        self.assertTrue(ok)
        self.assertIn("access_token=token-1", seen["url"])
        payload = json.loads(seen["payload"].decode("utf-8"))
        self.assertEqual(payload["targetId"], "chat-1")
        self.assertEqual(payload["msgKey"], "sampleMarkdown")

    def test_handle_event_ignores_unsupported_message_type(self) -> None:
        from src.gateway.adapter_dingtalk import DingTalkAdapter

        adapter = DingTalkAdapter()
        adapter._forward_to_gateway = MagicMock(return_value="")  # type: ignore[method-assign]

        result = adapter._handle_event(
            {
                "conversationType": "single",
                "conversationId": "chat-1",
                "senderStaffId": "u1",
                "msgtype": "image",
                "msgId": "m2",
            },
            "{}",
        )

        self.assertIsNone(result)
        adapter._forward_to_gateway.assert_not_called()

    def test_handle_event_accepts_file_message_and_forwards_placeholder(self) -> None:
        from src.gateway.adapter_dingtalk import DingTalkAdapter

        adapter = DingTalkAdapter()
        adapter._forward_to_gateway = MagicMock(return_value="已收到文件")  # type: ignore[method-assign]
        adapter.send_message = MagicMock(return_value=True)  # type: ignore[method-assign]

        result = adapter._handle_event(
            {
                "conversationType": "single",
                "conversationId": "chat-1",
                "senderStaffId": "u1",
                "msgtype": "file",
                "msgId": "m3",
                "file": {"fileName": "制度.docx"},
            },
            "{}",
        )

        self.assertIsNone(result)
        adapter._forward_to_gateway.assert_called_once()
        forwarded = adapter._forward_to_gateway.call_args.args
        self.assertEqual(forwarded[0], "u1")
        self.assertIn("制度.docx", forwarded[1])
        adapter.send_message.assert_called_once_with("chat-1", "已收到文件")

    def test_forward_to_gateway_retries_then_returns_reply(self) -> None:
        from src.gateway.adapter_dingtalk import DingTalkAdapter

        adapter = DingTalkAdapter(gateway_url="http://gateway.test")
        calls = {"count": 0}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps({"reply": "ok"}).encode("utf-8")

        def fake_urlopen(req, timeout=15):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("temporary")
            return Response()

        with (
            patch("src.gateway.adapter_dingtalk.urllib.request.urlopen", side_effect=fake_urlopen),
            patch("src.gateway.adapter_dingtalk.time.sleep"),
        ):
            reply = adapter._forward_to_gateway("u1", "hello", "chat-1", "single")

        self.assertEqual(reply, "ok")
        self.assertEqual(calls["count"], 2)
