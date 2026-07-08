from __future__ import annotations

from typing import Any

from src.gateway.adapter_dingtalk import DingTalkAdapter
from src.gateway.adapter_feishu import FeishuAdapter
from src.gateway.wecom_outbound import send_text


def _normalize_platform(platform: str) -> str:
    lowered = str(platform or "").strip().lower()
    if lowered in {"wecom", "wecom_bot", "wecom_bot_ws", "企业微信", "企微"}:
        return "wecom"
    if lowered in {"feishu", "lark", "飞书"}:
        return "feishu"
    if lowered in {"dingtalk", "钉钉"}:
        return "dingtalk"
    return lowered or "wecom"


def send_platform_text(platform: str, target_id: str, text: str) -> bool:
    normalized = _normalize_platform(platform)
    if normalized == "wecom":
        return send_text(target_id, text)
    if normalized == "feishu":
        return FeishuAdapter().send_message(target_id, text)
    if normalized == "dingtalk":
        return DingTalkAdapter().send_message(target_id, text, title="AI 助手")
    return False


def send_platform_entry_payload(platform: str, target_id: str, payloads: dict[str, Any]) -> bool:
    normalized = _normalize_platform(platform)
    if normalized == "wecom":
        return send_text(target_id, str(payloads.get("text", "")))
    if normalized == "feishu":
        return FeishuAdapter().send_entry_card(target_id, payloads.get("feishu_card", {}))
    if normalized == "dingtalk":
        return DingTalkAdapter().send_entry_card(target_id, payloads.get("dingtalk_card", {}))
    return False
