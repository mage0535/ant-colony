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

    def test_send_message_splits_long_text_into_multiple_requests(self) -> None:
        from src.gateway.adapter_dingtalk import DingTalkAdapter

        adapter = DingTalkAdapter()

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps({"errcode": 0, "errmsg": "ok"}).encode("utf-8")

        payloads: list[dict[str, object]] = []

        def fake_urlopen(req, timeout=10):
            payloads.append(json.loads(req.data.decode("utf-8")))
            return Response()

        with (
            patch.object(adapter, "_ensure_token", return_value="token-1"),
            patch("src.gateway.adapter_dingtalk.urllib.request.urlopen", side_effect=fake_urlopen),
        ):
            ok = adapter.send_message("chat-1", "很长的内容。" * 300)

        self.assertTrue(ok)
        self.assertGreaterEqual(len(payloads), 2)
        second_msg = json.loads(payloads[1]["msgParam"])
        first_msg = json.loads(payloads[0]["msgParam"])
        self.assertTrue(first_msg["text"].startswith("（1/"))
        self.assertTrue(second_msg["text"].startswith("（2/"))

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

    def test_handle_event_downloads_file_content_when_download_code_present(self) -> None:
        from src.gateway.adapter_dingtalk import DingTalkAdapter

        adapter = DingTalkAdapter()
        adapter._forward_to_gateway = MagicMock(return_value="已处理文件")  # type: ignore[method-assign]
        adapter.send_message = MagicMock(return_value=True)  # type: ignore[method-assign]

        with patch.object(adapter, "_download_message_file", return_value=(b"doc-bytes", "制度.docx")) as download, \
             patch("src.gateway.adapter_dingtalk.summarize_platform_file_bytes", return_value="用户发送了文件：制度.docx\n\n以下是文件内容：\n---\n正文\n---\n"):
            result = adapter._handle_event(
                {
                    "conversationType": "single",
                    "conversationId": "chat-2",
                    "senderStaffId": "u2",
                    "msgtype": "file",
                    "msgId": "m4",
                    "robotCode": "robot-1",
                    "file": {"fileName": "制度.docx", "downloadCode": "dc-1"},
                },
                "{}",
            )

        self.assertIsNone(result)
        download.assert_called_once_with("dc-1", "robot-1", "制度.docx")
        adapter._forward_to_gateway.assert_called_once()
        forwarded = adapter._forward_to_gateway.call_args.args
        self.assertIn("以下是文件内容", forwarded[1])
        adapter.send_message.assert_called_once_with("chat-2", "已处理文件")

    def test_handle_event_sends_entry_card_for_menu_command(self) -> None:
        from src.gateway.adapter_dingtalk import DingTalkAdapter

        adapter = DingTalkAdapter()
        adapter.send_entry_card = MagicMock(return_value=True)  # type: ignore[method-assign]
        adapter._forward_to_gateway = MagicMock(return_value="")  # type: ignore[method-assign]

        with patch("src.gateway.adapter_dingtalk.build_platform_entry_payloads", return_value={"dingtalk_card": {"title": "Ant Colony 入口"}}), \
             patch("src.web.admin_auth.is_platform_admin", return_value=False):
            result = adapter._handle_event(
                {
                    "conversationType": "single",
                    "conversationId": "chat-3",
                    "senderStaffId": "u3",
                    "msgtype": "text",
                    "text": {"content": "帮助"},
                    "msgId": "m5",
                },
                "{}",
            )

        self.assertIsNone(result)
        adapter.send_entry_card.assert_called_once_with("chat-3", {"title": "Ant Colony 入口"})
        adapter._forward_to_gateway.assert_not_called()

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
