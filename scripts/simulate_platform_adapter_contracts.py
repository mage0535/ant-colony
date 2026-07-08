from __future__ import annotations

import json
import os
from typing import Any, Callable


def _scenario(name: str, ok: bool, **details: Any) -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), **details}


def simulate_feishu_contract() -> dict[str, Any]:
    from src.gateway.adapter_feishu import FeishuAdapter

    os.environ.setdefault("ANT_COLONY_ADMIN_SESSION_SECRET", "simulation-secret")
    adapter = FeishuAdapter(gateway_url="http://gateway.invalid")
    forwards: list[dict[str, str]] = []
    sent: list[dict[str, str]] = []
    cards: list[dict[str, Any]] = []

    def forward(user_id: str, text: str, chat_id: str, chat_type: str) -> str:
        forwards.append({"user_id": user_id, "text": text, "chat_id": chat_id, "chat_type": chat_type})
        return "feishu-reply"

    def send(chat_id: str, text: str, msg_type: str = "text") -> bool:
        sent.append({"chat_id": chat_id, "text": text, "msg_type": msg_type})
        return True

    def send_card(chat_id: str, payload: dict[str, Any]) -> bool:
        cards.append({"chat_id": chat_id, "payload": payload})
        return True

    adapter._forward_to_gateway = forward  # type: ignore[method-assign]
    adapter.send_message = send  # type: ignore[method-assign]
    adapter.send_entry_card = send_card  # type: ignore[method-assign]

    direct_event = {
        "header": {"event_type": "im.message.receive_v1"},
        "event": {
            "message": {
                "message_id": "fs-m1",
                "message_type": "text",
                "chat_type": "p2p",
                "chat_id": "fs-chat-1",
                "content": json.dumps({"text": "hello"}, ensure_ascii=False),
            },
            "sender": {"sender_id": {"user_id": "fs-user-1"}},
        },
    }
    adapter._handle_event(direct_event, json.dumps(direct_event, ensure_ascii=False))

    group_with_mention = {
        "header": {"event_type": "im.message.receive_v1"},
        "event": {
            "message": {
                "message_id": "fs-m1b",
                "message_type": "text",
                "chat_type": "group",
                "chat_id": "fs-chat-1g",
                "content": json.dumps({"text": "@AI 请总结"}, ensure_ascii=False),
                "mentions": [{"name": "AI"}],
            },
            "sender": {"sender_id": {"user_id": "fs-user-2"}},
        },
    }
    adapter._handle_event(group_with_mention, json.dumps(group_with_mention, ensure_ascii=False))

    ignored_group = {
        "header": {"event_type": "im.message.receive_v1"},
        "event": {
            "message": {
                "message_id": "fs-m2",
                "message_type": "text",
                "chat_type": "group",
                "chat_id": "fs-chat-2",
                "content": json.dumps({"text": "group hello"}, ensure_ascii=False),
                "mentions": [],
            },
            "sender": {"sender_id": {"user_id": "fs-user-1"}},
        },
    }
    before_ignored = len(forwards)
    adapter._handle_event(ignored_group, json.dumps(ignored_group, ensure_ascii=False))
    after_ignored = len(forwards)

    before_file = len(forwards)
    file_event = {
        "header": {"event_type": "im.message.receive_v1"},
        "event": {
            "message": {
                "message_id": "fs-m3",
                "message_type": "file",
                "chat_type": "p2p",
                "chat_id": "fs-chat-3",
                "file_name": "制度.docx",
            },
            "sender": {"sender_id": {"user_id": "fs-user-1"}},
        },
    }
    adapter._handle_event(file_event, json.dumps(file_event, ensure_ascii=False))

    menu_event = {
        "header": {"event_type": "im.message.receive_v1"},
        "event": {
            "message": {
                "message_id": "fs-m4",
                "message_type": "text",
                "chat_type": "p2p",
                "chat_id": "fs-chat-4",
                "content": json.dumps({"text": "菜单"}, ensure_ascii=False),
            },
            "sender": {"sender_id": {"user_id": "fs-user-3"}},
        },
    }
    before_menu_forward = len(forwards)
    adapter._handle_event(menu_event, json.dumps(menu_event, ensure_ascii=False))

    return {
        "platform": "feishu",
        "ok": len(forwards) == 3 and len(sent) == 3 and len(cards) == 1 and len(forwards) == before_ignored + 1 and len(forwards) == before_file + 1,
        "scenarios": [
            _scenario(
                "direct_text_forward_and_reply",
                len(forwards) >= 1 and forwards[0]["text"] == "hello" and len(sent) >= 1,
                forwarded=forwards[0] if forwards else {},
                sent=sent[0] if sent else {},
            ),
            _scenario(
                "group_with_mention_forward_and_reply",
                len(forwards) >= 2 and forwards[1]["chat_type"] == "group" and len(sent) >= 2,
                forwarded=forwards[1] if len(forwards) > 1 else {},
                sent=sent[1] if len(sent) > 1 else {},
            ),
            _scenario("group_without_mention_ignored", after_ignored == before_ignored),
            _scenario(
                "file_message_forwarded_as_placeholder",
                len(forwards) > 2 and "制度.docx" in forwards[2]["text"] and len(sent) > 2,
                forwarded=forwards[2] if len(forwards) > 2 else {},
                sent=sent[2] if len(sent) > 2 else {},
            ),
            _scenario(
                "menu_command_sends_entry_card",
                len(cards) == 1 and len(forwards) == before_menu_forward,
                sent=cards[0] if cards else {},
            ),
        ],
    }


def simulate_dingtalk_contract() -> dict[str, Any]:
    from src.gateway.adapter_dingtalk import DingTalkAdapter

    os.environ.setdefault("ANT_COLONY_ADMIN_SESSION_SECRET", "simulation-secret")
    adapter = DingTalkAdapter(gateway_url="http://gateway.invalid")
    forwards: list[dict[str, str]] = []
    sent: list[dict[str, str]] = []
    cards: list[dict[str, Any]] = []

    def forward(user_id: str, text: str, chat_id: str, chat_type: str) -> str:
        forwards.append({"user_id": user_id, "text": text, "chat_id": chat_id, "chat_type": chat_type})
        return "dingtalk-reply"

    def send(chat_id: str, text: str, title: str = "AI Assistant") -> bool:
        sent.append({"chat_id": chat_id, "text": text, "title": title})
        return True

    def send_card(chat_id: str, payload: dict[str, Any]) -> bool:
        cards.append({"chat_id": chat_id, "payload": payload})
        return True

    adapter._forward_to_gateway = forward  # type: ignore[method-assign]
    adapter.send_message = send  # type: ignore[method-assign]
    adapter.send_entry_card = send_card  # type: ignore[method-assign]

    direct_event = {
        "conversationType": "single",
        "conversationId": "dt-chat-1",
        "senderStaffId": "dt-user-1",
        "msgtype": "text",
        "text": {"content": "hello"},
        "msgId": "dt-m1",
    }
    adapter._handle_event(direct_event, json.dumps(direct_event, ensure_ascii=False))

    group_with_mention = {
        "conversationType": "group",
        "conversationId": "dt-chat-1g",
        "senderStaffId": "dt-user-2",
        "msgtype": "text",
        "text": {"content": "@AI 请总结"},
        "msgId": "dt-m1b",
        "atUsers": [{"dingtalkId": "bot"}],
    }
    adapter._handle_event(group_with_mention, json.dumps(group_with_mention, ensure_ascii=False))

    ignored_group = {
        "conversationType": "group",
        "conversationId": "dt-chat-2",
        "senderStaffId": "dt-user-1",
        "msgtype": "text",
        "text": {"content": "group hello"},
        "msgId": "dt-m2",
        "atUsers": [],
    }
    before_ignored = len(forwards)
    adapter._handle_event(ignored_group, json.dumps(ignored_group, ensure_ascii=False))
    after_ignored = len(forwards)

    before_file = len(forwards)
    file_event = {
        "conversationType": "single",
        "conversationId": "dt-chat-3",
        "senderStaffId": "dt-user-1",
        "msgtype": "file",
        "msgId": "dt-m3",
        "file": {"fileName": "制度.docx"},
    }
    adapter._handle_event(file_event, json.dumps(file_event, ensure_ascii=False))

    menu_event = {
        "conversationType": "single",
        "conversationId": "dt-chat-4",
        "senderStaffId": "dt-user-3",
        "msgtype": "text",
        "text": {"content": "帮助"},
        "msgId": "dt-m4",
    }
    before_menu_forward = len(forwards)
    adapter._handle_event(menu_event, json.dumps(menu_event, ensure_ascii=False))

    return {
        "platform": "dingtalk",
        "ok": len(forwards) == 3 and len(sent) == 3 and len(cards) == 1 and len(forwards) == before_ignored + 1 and len(forwards) == before_file + 1,
        "scenarios": [
            _scenario(
                "direct_text_forward_and_reply",
                len(forwards) >= 1 and forwards[0]["text"] == "hello" and len(sent) >= 1,
                forwarded=forwards[0] if forwards else {},
                sent=sent[0] if sent else {},
            ),
            _scenario(
                "group_with_mention_forward_and_reply",
                len(forwards) >= 2 and forwards[1]["chat_type"] == "group" and len(sent) >= 2,
                forwarded=forwards[1] if len(forwards) > 1 else {},
                sent=sent[1] if len(sent) > 1 else {},
            ),
            _scenario("group_without_mention_ignored", after_ignored == before_ignored),
            _scenario(
                "file_message_forwarded_as_placeholder",
                len(forwards) > 2 and "制度.docx" in forwards[2]["text"] and len(sent) > 2,
                forwarded=forwards[2] if len(forwards) > 2 else {},
                sent=sent[2] if len(sent) > 2 else {},
            ),
            _scenario(
                "menu_command_sends_entry_card",
                len(cards) == 1 and len(forwards) == before_menu_forward,
                sent=cards[0] if cards else {},
            ),
        ],
    }


def build_report(simulators: list[Callable[[], dict[str, Any]]] | None = None) -> dict[str, Any]:
    selected = simulators or [simulate_feishu_contract, simulate_dingtalk_contract]
    platforms = [simulate() for simulate in selected]
    return {
        "ok": all(item.get("ok") for item in platforms),
        "mode": "local-simulation",
        "platforms": platforms,
    }


def main() -> int:
    report = build_report()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
