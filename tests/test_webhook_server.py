from __future__ import annotations


def test_save_message_best_effort_does_not_raise_when_repo_fails() -> None:
    from src.gateway.webhook_server import _save_message_best_effort

    class FailingRepo:
        def save_message(self, *_args):
            raise RuntimeError("database is locked")

    assert _save_message_best_effort(FailingRepo(), "space", "user", "管理后台") is False  # type: ignore[arg-type]


def test_save_message_best_effort_returns_true_when_repo_succeeds() -> None:
    from src.gateway.webhook_server import _save_message_best_effort

    class WorkingRepo:
        def __init__(self) -> None:
            self.saved = False

        def save_message(self, *_args):
            self.saved = True

    repo = WorkingRepo()

    assert _save_message_best_effort(repo, "space", "user", "管理后台") is True  # type: ignore[arg-type]
    assert repo.saved is True


def test_fallback_reply_for_direct_payload_returns_visible_message() -> None:
    from src.gateway.webhook_server import _fallback_reply_for_payload

    result = _fallback_reply_for_payload(
        {
            "from_user_id": "u1",
            "content": "帮我查一下",
            "is_direct": True,
            "provider": "wecom_bot",
        }
    )

    assert result is not None
    assert result["route_kind"] == "personal"
    assert result["target_id"] == "u1"
    assert result["fallback"] is True
    assert "请稍后再发一次" in result["reply"]


def test_fallback_reply_ignores_group_payload() -> None:
    from src.gateway.webhook_server import _fallback_reply_for_payload

    assert _fallback_reply_for_payload({"from_user_id": "u1", "is_direct": False}) is None


def test_fast_direct_reply_handles_greeting_without_gateway() -> None:
    from src.gateway.webhook_server import _fast_direct_reply_for_payload

    result = _fast_direct_reply_for_payload(
        {"from_user_id": "u1", "content": "\u4f60\u597d", "is_direct": True, "provider": "wecom_bot"}
    )

    assert result is not None
    assert result["route_kind"] == "personal"
    assert result["target_id"] == "u1"
    assert "\u6211\u5728" in result["reply"]


def test_fast_direct_reply_handles_mail_reply_capability_without_mail_tool() -> None:
    from src.gateway.webhook_server import _fast_direct_reply_for_payload

    result = _fast_direct_reply_for_payload(
        {"from_user_id": "u1", "content": "\u4f60\u53ef\u4ee5\u5e2e\u6211\u56de\u90ae\u5417", "is_direct": True}
    )

    assert result is not None
    assert "\u8d77\u8349\u56de\u90ae" in result["reply"]
    assert "\u4e0d\u4f1a\u66ff\u4f60\u76f4\u63a5\u53d1\u9001" in result["reply"]


def test_fast_direct_reply_handles_knowledge_entry(monkeypatch) -> None:
    monkeypatch.setenv("ANT_COLONY_ADMIN_SESSION_SECRET", "test-secret")
    from src.gateway.webhook_server import _fast_direct_reply_for_payload

    result = _fast_direct_reply_for_payload(
        {"from_user_id": "u1", "content": "\u77e5\u8bc6\u5e93\u540e\u53f0", "is_direct": True, "provider": "wecom_bot"}
    )

    assert result is not None
    assert "/knowledge/user?" in result["reply"]


def test_webhook_respond_suppresses_client_disconnect() -> None:
    from src.gateway.webhook_server import WecomWebhookHandler

    handler = object.__new__(WecomWebhookHandler)
    handler.send_response = lambda code: None  # type: ignore[method-assign]
    handler.send_header = lambda key, value: None  # type: ignore[method-assign]
    handler.end_headers = lambda: None  # type: ignore[method-assign]

    class BrokenWriter:
        def write(self, _body):
            raise BrokenPipeError("client disconnected")

    handler.wfile = BrokenWriter()  # type: ignore[assignment]

    handler._respond(200, {"reply": "ok"})
