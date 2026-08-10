from __future__ import annotations

import json
from unittest.mock import patch


def test_send_text_splits_long_message_into_multiple_wecom_requests() -> None:
    from src.gateway.wecom_outbound import send_text

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
        patch("src.gateway.wecom_outbound._get_token", return_value="token-1"),
        patch("src.gateway.wecom_outbound.urllib.request.urlopen", side_effect=fake_urlopen),
        patch("src.gateway.wecom_outbound.TEXT_CHUNK_DELAY_SECONDS", 0),
    ):
        ok = send_text("u1", "\u5f88\u957f\u7684\u5185\u5bb9\u3002" * 300)

    assert ok is True
    assert len(payloads) >= 2
    assert str(payloads[0]["text"]["content"]).startswith("\uff081/")
    assert str(payloads[1]["text"]["content"]).startswith("\uff082/")
    assert all(len(payload["text"]["content"].encode("utf-8")) <= 2048 for payload in payloads)


def test_employee_welcome_message_is_split_into_multiple_visible_wecom_text_messages() -> None:
    from src.gateway.wecom_outbound import send_text
    from src.platform.employee_bot_service import build_employee_bot_welcome_message

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

    message = build_employee_bot_welcome_message("\u4f01\u4e1a AI \u52a9\u624b")
    assert len(message.encode("utf-8")) > 2048

    with (
        patch("src.gateway.wecom_outbound._get_token", return_value="token-1"),
        patch("src.gateway.wecom_outbound.urllib.request.urlopen", side_effect=fake_urlopen),
        patch("src.gateway.wecom_outbound.TEXT_CHUNK_DELAY_SECONDS", 0),
    ):
        ok = send_text("u1", message)

    sent_text = "\n".join(str(payload["text"]["content"]) for payload in payloads)
    assert ok is True
    assert len(payloads) >= 2
    assert all(len(payload["text"]["content"].encode("utf-8")) <= 2048 for payload in payloads)
    assert str(payloads[0]["text"]["content"]).startswith("\uff081/")
    assert str(payloads[1]["text"]["content"]).startswith("\uff082/")
    assert "\u4f60\u7684\u4f01\u4e1a AI \u52a9\u624b\u5df2\u5f00\u901a" in sent_text
    assert "\u5982\u679c\u67d0\u9879\u80fd\u529b\u63d0\u793a\u672a\u914d\u7f6e" in sent_text
    assert "\u4e1a\u52a1\u7cfb\u7edf\u901a\u77e5\u4e0e\u67e5\u8be2" in sent_text
