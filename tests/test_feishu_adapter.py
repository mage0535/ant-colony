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

    def test_send_message_splits_long_text_into_multiple_requests(self) -> None:
        from src.gateway.adapter_feishu import FeishuAdapter

        adapter = FeishuAdapter()

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps({"code": 0, "data": {}}).encode("utf-8")

        payloads: list[dict[str, object]] = []

        def fake_urlopen(req, timeout=10):
            payloads.append(json.loads(req.data.decode("utf-8")))
            return Response()

        with (
            patch.object(adapter, "_get_tenant_token", return_value="tenant-token"),
            patch("src.gateway.adapter_feishu.urlopen", side_effect=fake_urlopen),
        ):
            ok = adapter.send_message("chat-1", "很长的内容。" * 300)

        self.assertTrue(ok)
        self.assertGreaterEqual(len(payloads), 2)
        second_content = json.loads(payloads[1]["content"])
        first_content = json.loads(payloads[0]["content"])
        self.assertTrue(first_content["text"].startswith("（1/"))
        self.assertTrue(second_content["text"].startswith("（2/"))

    def test_handle_event_ignores_unsupported_message_type(self) -> None:
        from src.gateway.adapter_feishu import FeishuAdapter

        adapter = FeishuAdapter()
        adapter._forward_to_gateway = MagicMock(return_value="")  # type: ignore[method-assign]

        result = adapter._handle_event(
            {
                "header": {"event_type": "im.message.receive_v1"},
                "event": {
                    "message": {"message_id": "m2", "message_type": "image", "chat_type": "p2p", "chat_id": "chat-1"},
                    "sender": {"sender_id": {"user_id": "u1"}},
                },
            },
            "{}",
        )

        self.assertIsNone(result)
        adapter._forward_to_gateway.assert_not_called()

    def test_handle_event_accepts_file_message_and_forwards_placeholder(self) -> None:
        from src.gateway.adapter_feishu import FeishuAdapter

        adapter = FeishuAdapter()
        adapter._forward_to_gateway = MagicMock(return_value="已收到文件")  # type: ignore[method-assign]
        adapter.send_message = MagicMock(return_value=True)  # type: ignore[method-assign]

        result = adapter._handle_event(
            {
                "header": {"event_type": "im.message.receive_v1"},
                "event": {
                    "message": {
                        "message_id": "m3",
                        "message_type": "file",
                        "chat_type": "p2p",
                        "chat_id": "chat-1",
                        "file_name": "制度.docx",
                    },
                    "sender": {"sender_id": {"user_id": "u1"}},
                },
            },
            "{}",
        )

        self.assertIsNone(result)
        adapter._forward_to_gateway.assert_called_once()
        forwarded = adapter._forward_to_gateway.call_args.args
        self.assertEqual(forwarded[0], "u1")
        self.assertIn("制度.docx", forwarded[1])
        adapter.send_message.assert_called_once_with("chat-1", "已收到文件")

    def test_handle_event_downloads_file_content_when_file_key_present(self) -> None:
        from src.gateway.adapter_feishu import FeishuAdapter

        adapter = FeishuAdapter()
        adapter._forward_to_gateway = MagicMock(return_value="已处理文件")  # type: ignore[method-assign]
        adapter.send_message = MagicMock(return_value=True)  # type: ignore[method-assign]

        with patch.object(adapter, "_download_message_file", return_value=(b"doc-bytes", "制度.docx")) as download, \
             patch("src.gateway.adapter_feishu.summarize_platform_file_bytes", return_value="用户发送了文件：制度.docx\n\n以下是文件内容：\n---\n正文\n---\n"):
            result = adapter._handle_event(
                {
                    "header": {"event_type": "im.message.receive_v1"},
                    "event": {
                        "message": {
                            "message_id": "m4",
                            "message_type": "file",
                            "chat_type": "p2p",
                            "chat_id": "chat-2",
                            "content": json.dumps({"file_key": "fk-1", "file_name": "制度.docx"}, ensure_ascii=False),
                        },
                        "sender": {"sender_id": {"user_id": "u2"}},
                    },
                },
                "{}",
            )

        self.assertIsNone(result)
        download.assert_called_once_with("m4", "fk-1", "制度.docx")
        adapter._forward_to_gateway.assert_called_once()
        forwarded = adapter._forward_to_gateway.call_args.args
        self.assertIn("以下是文件内容", forwarded[1])
        adapter.send_message.assert_called_once_with("chat-2", "已处理文件")

    def test_handle_event_sends_entry_card_for_menu_command(self) -> None:
        from src.gateway.adapter_feishu import FeishuAdapter

        adapter = FeishuAdapter()
        adapter.send_entry_card = MagicMock(return_value=True)  # type: ignore[method-assign]
        adapter._forward_to_gateway = MagicMock(return_value="")  # type: ignore[method-assign]

        with patch("src.gateway.adapter_feishu.build_platform_entry_payloads", return_value={"feishu_card": {"header": {"title": {"content": "Ant Colony 入口"}}}}), \
             patch("src.web.admin_auth.is_platform_admin", return_value=True):
            result = adapter._handle_event(
                {
                    "header": {"event_type": "im.message.receive_v1"},
                    "event": {
                        "message": {
                            "message_id": "m5",
                            "message_type": "text",
                            "chat_type": "p2p",
                            "chat_id": "chat-3",
                            "content": json.dumps({"text": "菜单"}, ensure_ascii=False),
                        },
                        "sender": {"sender_id": {"user_id": "u3"}},
                    },
                },
                "{}",
            )

        self.assertIsNone(result)
        adapter.send_entry_card.assert_called_once_with("chat-3", {"header": {"title": {"content": "Ant Colony 入口"}}})
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
