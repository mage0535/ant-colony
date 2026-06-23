from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class TestWeComBotPayloadHelpers(unittest.TestCase):
    def test_extract_bot_file_ref_from_file_message(self) -> None:
        from src.gateway.wecom_bot_bridge import extract_bot_file_ref

        ref = extract_bot_file_ref(
            {
                "msgtype": "file",
                "file": {"name": "模板.docx", "url": "https://example.com/docx", "aeskey": "abc"},
            }
        )

        self.assertIsNotNone(ref)
        self.assertEqual(ref["name"], "模板.docx")
        self.assertEqual(ref["url"], "https://example.com/docx")
        self.assertEqual(ref["aeskey"], "abc")

    def test_extract_bot_file_ref_from_appmsg_message(self) -> None:
        from src.gateway.wecom_bot_bridge import extract_bot_file_ref

        ref = extract_bot_file_ref(
            {
                "msgtype": "appmsg",
                "appmsg": {
                    "title": "规章制度.docx",
                    "file": {"url": "https://example.com/appmsg.docx"},
                },
            }
        )

        self.assertIsNotNone(ref)
        self.assertEqual(ref["name"], "规章制度.docx")
        self.assertEqual(ref["url"], "https://example.com/appmsg.docx")

    def test_extract_bot_file_ref_infers_name_from_url_when_missing(self) -> None:
        from src.gateway.wecom_bot_bridge import extract_bot_file_ref

        ref = extract_bot_file_ref(
            {
                "msgtype": "file",
                "file": {"url": "https://example.com/files/%E5%88%B6%E5%BA%A6.docx"},
            }
        )

        self.assertIsNotNone(ref)
        self.assertEqual(ref["name"], "制度.docx")

    def test_build_gateway_payload_marks_group_messages_non_direct(self) -> None:
        from src.gateway.wecom_bot_bridge import build_gateway_payload_for_bot

        payload = build_gateway_payload_for_bot(
            body={
                "msgid": "msg-1",
                "chatid": "group-1",
                "chattype": "group",
                "from": {"userid": "u123"},
            },
            msg_type="text",
            content="hello",
        )

        self.assertFalse(payload["is_direct"])
        self.assertEqual(payload["space_id"], "group-1")
        self.assertEqual(payload["from_user_id"], "u123")


class TestWeComBotBridge(unittest.IsolatedAsyncioTestCase):
    async def test_file_download_rejects_oversized_payloads(self) -> None:
        from src.gateway.wecom_bot_bridge import WeComBotBridge

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self, size=-1):
                return b"x" * 11

        bridge = WeComBotBridge("http://127.0.0.1:18090", "bot-1", "secret-1")
        with (
            patch("src.gateway.wecom_bot_bridge.MAX_INBOUND_FILE_BYTES", 10, create=True),
            patch("src.gateway.wecom_bot_bridge.urllib.request.urlopen", return_value=Response()),
        ):
            with self.assertRaisesRegex(ValueError, "exceeds"):
                await bridge._summarize_file_ref(
                    {"name": "large.docx", "url": "https://example.com/large.docx", "aeskey": "", "base64": ""},
                    "u123",
                )

    async def test_file_download_rejects_non_https_urls(self) -> None:
        from src.gateway.wecom_bot_bridge import WeComBotBridge

        bridge = WeComBotBridge("http://127.0.0.1:18090", "bot-1", "secret-1")

        with patch("src.gateway.wecom_bot_bridge.urllib.request.urlopen") as urlopen:
            with self.assertRaisesRegex(ValueError, "HTTPS"):
                await bridge._summarize_file_ref(
                    {"name": "secret.txt", "url": "file:///etc/passwd", "aeskey": "", "base64": ""},
                    "u123",
                )

        urlopen.assert_not_called()

    async def test_file_message_buffers_and_replies_ack(self) -> None:
        from src.gateway.wecom_bot_bridge import WeComBotBridge

        bridge = WeComBotBridge("http://127.0.0.1:18090", "bot-1", "secret-1")
        bridge._reply_text = AsyncMock()
        bridge._forward_to_gateway = AsyncMock(return_value=None)

        with patch.object(bridge, "_summarize_file_ref", AsyncMock(return_value="用户发送了文件：模板.docx")):
            await bridge._handle_message_callback(
                {
                    "msgid": "msg-1",
                    "chatid": "chat-1",
                    "chattype": "single",
                    "from": {"userid": "u123"},
                    "msgtype": "file",
                    "file": {"name": "模板.docx", "url": "https://example.com/docx"},
                },
                req_id="req-1",
            )

        bridge._forward_to_gateway.assert_not_awaited()
        bridge._reply_text.assert_awaited_once()
        self.assertIn("u123", bridge._file_buffer)

    async def test_text_message_consumes_buffered_file_and_forwards_combined_content(self) -> None:
        from src.gateway.wecom_bot_bridge import WeComBotBridge

        bridge = WeComBotBridge("http://127.0.0.1:18090", "bot-1", "secret-1")
        bridge._reply_text = AsyncMock()
        bridge._forward_to_gateway = AsyncMock(return_value=None)
        bridge._file_buffer["u123"] = ("用户发送了文件：模板.docx\n---\n第一章 总则\n---", 1.0)

        with patch("src.gateway.wecom_bot_bridge.time.time", return_value=2.0):
            await bridge._handle_message_callback(
                {
                    "msgid": "msg-2",
                    "chatid": "chat-1",
                    "chattype": "single",
                    "from": {"userid": "u123"},
                    "msgtype": "text",
                    "text": {"content": "分析这个文档并优化内容"},
                },
                req_id="req-2",
            )

        bridge._reply_text.assert_not_awaited()
        bridge._forward_to_gateway.assert_awaited_once()
        forwarded = bridge._forward_to_gateway.await_args.args[0]
        self.assertIn("用户发送了文件：模板.docx", forwarded["content"])
        self.assertIn("分析这个文档并优化内容", forwarded["content"])
        self.assertTrue(forwarded["is_file_message"])
        self.assertNotIn("u123", bridge._file_buffer)

    async def test_file_referential_text_is_buffered_until_delay_expires(self) -> None:
        from src.gateway.wecom_bot_bridge import WeComBotBridge

        bridge = WeComBotBridge("http://127.0.0.1:18090", "bot-1", "secret-1")
        bridge._reply_text = AsyncMock()
        bridge._forward_to_gateway = AsyncMock(return_value=None)

        with patch("src.gateway.wecom_bot_bridge.time.time", return_value=1.0):
            await bridge._handle_message_callback(
                {
                    "msgid": "msg-3",
                    "chatid": "chat-1",
                    "chattype": "single",
                    "from": {"userid": "u123"},
                    "msgtype": "text",
                    "text": {"content": "你来整理提取内容，总结精炼给我"},
                },
                req_id="req-3",
            )

        bridge._forward_to_gateway.assert_not_awaited()
        self.assertIn("u123", bridge._text_buffer)

    async def test_file_referential_text_waits_long_enough_for_late_file(self) -> None:
        from src.gateway.wecom_bot_bridge import WeComBotBridge

        bridge = WeComBotBridge("http://127.0.0.1:18090", "bot-1", "secret-1")
        bridge._reply_text = AsyncMock()
        bridge._forward_to_gateway = AsyncMock(return_value=None)

        with patch("src.gateway.wecom_bot_bridge.time.time", return_value=1.0):
            await bridge._handle_message_callback(
                {
                    "msgid": "msg-3",
                    "chatid": "chat-1",
                    "chattype": "single",
                    "from": {"userid": "u123"},
                    "msgtype": "text",
                    "text": {"content": "我需要你帮我生成一个车间通行和通行管理规定"},
                },
                req_id="req-3",
            )

        task = bridge._text_wait_tasks["u123"]
        self.assertFalse(task.done())

    async def test_forward_to_gateway_sends_bot_file_marker_as_document(self) -> None:
        from src.gateway.wecom_bot_bridge import WeComBotBridge

        bridge = WeComBotBridge("http://127.0.0.1:18090", "bot-1", "secret-1")
        bridge._reply_text = AsyncMock()
        bridge._send_document = AsyncMock()

        fake_resp = MagicMock()
        fake_resp.raise_for_status.return_value = None
        fake_resp.json.return_value = {
            "reply": "[BOT_FILE]{\"path\": \"/tmp/report.docx\", \"filename\": \"report.docx\", \"caption\": \"文档已生成\"}"
        }

        class _FakeClient:
            def __init__(self, *args, **kwargs):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc, tb):
                return False
            async def post(self, *args, **kwargs):
                return fake_resp

        with patch("src.gateway.wecom_bot_bridge.httpx.AsyncClient", _FakeClient):
            await bridge._forward_to_gateway({"content": "x"}, req_id="req-1", chat_id="chat-1")

        bridge._send_document.assert_awaited_once_with("req-1", "chat-1", "/tmp/report.docx", "report.docx", "文档已生成")
        bridge._reply_text.assert_not_awaited()

    async def test_handle_ws_message_dispatches_callback_without_blocking_reader(self) -> None:
        from src.gateway.wecom_bot_bridge import WeComBotBridge

        bridge = WeComBotBridge("http://127.0.0.1:18090", "bot-1", "secret-1")
        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_handler(body, req_id):
            started.set()
            await release.wait()

        bridge._handle_message_callback = slow_handler  # type: ignore[method-assign]

        await bridge._handle_ws_message(
            json.dumps(
                {
                    "cmd": "aibot_msg_callback",
                    "headers": {"req_id": "req-1"},
                    "body": {"msgtype": "text", "text": {"content": "hello"}},
                }
            )
        )

        await asyncio.wait_for(started.wait(), timeout=1)
        self.assertFalse(release.is_set())
        release.set()

    async def test_handle_ws_message_treats_matching_req_id_as_ack_even_with_cmd(self) -> None:
        from src.gateway.wecom_bot_bridge import WeComBotBridge

        bridge = WeComBotBridge("http://127.0.0.1:18090", "bot-1", "secret-1")
        fut = asyncio.get_running_loop().create_future()
        bridge._pending_acks["req-1"] = fut

        await bridge._handle_ws_message(
            json.dumps(
                {
                    "cmd": "aibot_upload_media_init",
                    "headers": {"req_id": "req-1"},
                    "body": {"upload_id": "up-1"},
                    "errcode": 0,
                }
            )
        )

        self.assertTrue(fut.done())
        self.assertEqual(fut.result()["body"]["upload_id"], "up-1")

    async def test_forward_to_gateway_uses_longer_timeout_for_file_generation_requests(self) -> None:
        from src.gateway.wecom_bot_bridge import WeComBotBridge

        bridge = WeComBotBridge("http://127.0.0.1:18090", "bot-1", "secret-1")

        fake_resp = MagicMock()
        fake_resp.raise_for_status.return_value = None
        fake_resp.json.return_value = {"reply": "ok"}
        seen = {}

        class _FakeClient:
            def __init__(self, *args, **kwargs):
                seen["timeout"] = kwargs.get("timeout")
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc, tb):
                return False
            async def post(self, *args, **kwargs):
                return fake_resp

        with patch("src.gateway.wecom_bot_bridge.httpx.AsyncClient", _FakeClient):
            await bridge._forward_to_gateway(
                {"content": "x", "is_file_message": True},
                req_id="req-1",
                chat_id="chat-1",
            )

        self.assertEqual(seen["timeout"], 600)

    async def test_forward_to_gateway_sends_progress_notice_for_file_generation(self) -> None:
        from src.gateway.wecom_bot_bridge import WeComBotBridge

        bridge = WeComBotBridge("http://127.0.0.1:18090", "bot-1", "secret-1")
        bridge._reply_text = AsyncMock()

        fake_resp = MagicMock()
        fake_resp.raise_for_status.return_value = None
        fake_resp.json.return_value = {"reply": "ok"}

        class _FakeClient:
            def __init__(self, *args, **kwargs):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc, tb):
                return False
            async def post(self, *args, **kwargs):
                return fake_resp

        with patch("src.gateway.wecom_bot_bridge.httpx.AsyncClient", _FakeClient):
            await bridge._forward_to_gateway(
                {
                    "content": "用户发送了文件：模板.docx\n\n我需要你帮我生成一个车间通行和通行管理规定",
                    "is_file_message": True,
                    "provider": "wecom_bot",
                },
                req_id="req-1",
                chat_id="chat-1",
            )

        bridge._reply_text.assert_any_await("", "已收到文件和要求，正在生成文档，请稍候 1-3 分钟。", chat_id="chat-1")

    async def test_send_document_uses_extended_media_timeouts(self) -> None:
        from src.gateway.wecom_bot_bridge import WeComBotBridge

        bridge = WeComBotBridge("http://127.0.0.1:18090", "bot-1", "secret-1")
        seen_calls = []

        async def fake_send_request(cmd, body, timeout=30):
            seen_calls.append((cmd, timeout))
            if cmd.endswith("init"):
                return {"body": {"upload_id": "up-1"}}
            if cmd.endswith("finish"):
                return {"body": {"media_id": "media-1"}}
            return {"body": {}}

        async def fake_send_reply_request(req_id, body, timeout=30):
            seen_calls.append(("reply", timeout))
            return {"errcode": 0}

        bridge._send_request = fake_send_request  # type: ignore[method-assign]
        bridge._send_reply_request = fake_send_reply_request  # type: ignore[method-assign]

        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.docx"
            p.write_bytes(b"hello")
            bridge._last_req_by_chat["chat-1"] = ("req-1", 999.0)
            with patch("src.gateway.wecom_bot_bridge.time.time", return_value=1000.0):
                await bridge._send_document("req-1", "chat-1", str(p), "x.docx", "caption")

        self.assertIn(("aibot_upload_media_init", 120), seen_calls)
        self.assertIn(("aibot_upload_media_finish", 120), seen_calls)
        self.assertIn(("reply", 60), seen_calls)

    async def test_send_document_falls_back_to_proactive_send_when_reply_context_is_stale(self) -> None:
        from src.gateway.wecom_bot_bridge import WeComBotBridge

        bridge = WeComBotBridge("http://127.0.0.1:18090", "bot-1", "secret-1")
        bridge._reply_text = AsyncMock()
        seen_calls = []

        async def fake_send_request(cmd, body, timeout=30):
            seen_calls.append((cmd, body, timeout))
            if cmd.endswith("init"):
                return {"body": {"upload_id": "up-1"}}
            if cmd.endswith("finish"):
                return {"body": {"media_id": "media-1"}}
            return {"body": {}}

        async def fake_send_reply_request(req_id, body, timeout=60):
            seen_calls.append(("reply", body, timeout))
            return {"errcode": 0}

        bridge._send_request = fake_send_request  # type: ignore[method-assign]
        bridge._send_reply_request = fake_send_reply_request  # type: ignore[method-assign]

        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.docx"
            p.write_bytes(b"hello")
            bridge._last_req_by_chat["chat-1"] = ("req-1", 0.0)
            with patch("src.gateway.wecom_bot_bridge.time.time", return_value=999.0):
                await bridge._send_document("req-1", "chat-1", str(p), "x.docx", "caption")

        proactive_file = [call for call in seen_calls if call[0] == "aibot_send_msg" and call[1].get("msgtype") == "file"]
        self.assertTrue(proactive_file)
