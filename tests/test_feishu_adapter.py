from __future__ import annotations

import base64
import hashlib
import hmac
import json
import unittest
from unittest.mock import MagicMock, patch


class TestFeishuAdapter(unittest.TestCase):
    def test_verify_signature_accepts_valid_value(self) -> None:
        from src.gateway.adapter_feishu import _verify_signature

        app_secret = "secret"
        timestamp = "1000"
        nonce = "nonce-a"
        body = '{"event":"x"}'
        raw = timestamp + nonce + body
        signature = base64.b64encode(
            hmac.new(app_secret.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).digest()
        ).decode("utf-8")

        self.assertTrue(_verify_signature(app_secret, timestamp, nonce, body, signature))

    def test_handle_event_ignores_group_message_without_mentions(self) -> None:
        from src.gateway.adapter_feishu import FeishuAdapter

        adapter = FeishuAdapter()
        adapter._forward_to_gateway = MagicMock(return_value="")  # type: ignore[method-assign]

        result = adapter._handle_event(
            {
                "header": {"event_type": "im.message.receive_v1"},
                "event": {
                    "message": {
                        "message_id": "m1",
                        "message_type": "text",
                        "chat_type": "group",
                        "chat_id": "chat-1",
                        "content": json.dumps({"text": "hello"}, ensure_ascii=False),
                        "mentions": [],
                    },
                    "sender": {"sender_id": {"user_id": "u1"}},
                },
            },
            "{}",
        )

        self.assertIsNone(result)
        adapter._forward_to_gateway.assert_not_called()

    def test_send_message_uses_expected_payload(self) -> None:
        from src.gateway.adapter_feishu import FeishuAdapter

        adapter = FeishuAdapter()

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps({"code": 0, "data": {}}).encode("utf-8")

        seen = {}

        def fake_urlopen(req, timeout=10):
            seen["url"] = req.full_url
            seen["headers"] = dict(req.header_items())
            seen["payload"] = req.data
            return Response()

        with (
            patch.object(adapter, "_get_tenant_token", return_value="tenant-token"),
            patch("src.gateway.adapter_feishu.urlopen", side_effect=fake_urlopen),
        ):
            ok = adapter.send_message("chat-1", "hello world")

        self.assertTrue(ok)
        self.assertIn("receive_id_type=chat_id", seen["url"])
        self.assertIn("Bearer tenant-token", seen["headers"]["Authorization"])
        payload = json.loads(seen["payload"].decode("utf-8"))
        self.assertEqual(payload["receive_id"], "chat-1")
        self.assertEqual(payload["msg_type"], "text")

    def test_handle_event_ignores_non_text_message(self) -> None:
        from src.gateway.adapter_feishu import FeishuAdapter

        adapter = FeishuAdapter()
        adapter._forward_to_gateway = MagicMock(return_value="")  # type: ignore[method-assign]

        result = adapter._handle_event(
            {
                "header": {"event_type": "im.message.receive_v1"},
                "event": {
                    "message": {"message_id": "m2", "message_type": "file", "chat_type": "p2p", "chat_id": "chat-1"},
                    "sender": {"sender_id": {"user_id": "u1"}},
                },
            },
            "{}",
        )

        self.assertIsNone(result)
        adapter._forward_to_gateway.assert_not_called()

    def test_forward_to_gateway_retries_then_returns_reply(self) -> None:
        from src.gateway.adapter_feishu import FeishuAdapter

        adapter = FeishuAdapter(gateway_url="http://gateway.test")
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
            patch("src.gateway.adapter_feishu.urlopen", side_effect=fake_urlopen),
            patch("src.gateway.adapter_feishu.time.sleep"),
        ):
            reply = adapter._forward_to_gateway("u1", "hello", "chat-1", "p2p")

        self.assertEqual(reply, "ok")
        self.assertEqual(calls["count"], 2)
