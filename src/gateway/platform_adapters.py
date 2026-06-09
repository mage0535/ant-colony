from __future__ import annotations

import logging
import os
import threading
from typing import Any

logger = logging.getLogger(__name__)


def start_platform_adapters(gateway_url: str = "http://localhost:18090/webhook") -> list[threading.Thread]:
    threads = []

    # Feishu
    if os.environ.get("FEISHU_APP_ID") and os.environ.get("FEISHU_APP_SECRET"):
        try:
            from src.gateway.adapter_feishu import FeishuAdapter
            adapter = FeishuAdapter(gateway_url=gateway_url)
            t = threading.Thread(target=adapter.start, daemon=True, name="feishu-adapter")
            t.start()
            threads.append(t)
            logger.info("Feishu adapter started on port 18765")
        except Exception as e:
            logger.error("Failed to start Feishu adapter: %s", e)
    else:
        logger.info("Feishu adapter skipped (FEISHU_APP_ID not set)")

    # DingTalk
    if os.environ.get("DINGTALK_CLIENT_ID") and os.environ.get("DINGTALK_CLIENT_SECRET"):
        try:
            from src.gateway.adapter_dingtalk import DingTalkAdapter
            adapter = DingTalkAdapter(gateway_url=gateway_url)
            t = threading.Thread(target=adapter.start, daemon=True, name="dingtalk-adapter")
            t.start()
            threads.append(t)
            logger.info("DingTalk adapter started on port 18766")
        except Exception as e:
            logger.error("Failed to start DingTalk adapter: %s", e)
    else:
        logger.info("DingTalk adapter skipped (DINGTALK_CLIENT_ID not set)")

    # Telegram
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        try:
            from src.gateway.adapter_telegram import TelegramAdapter
            adapter = TelegramAdapter(gateway_url=gateway_url)
            t = threading.Thread(target=adapter.start, daemon=True, name="telegram-adapter")
            t.start()
            threads.append(t)
            logger.info("Telegram adapter started (polling)")
        except Exception as e:
            logger.error("Failed to start Telegram adapter: %s", e)
    else:
        logger.info("Telegram adapter skipped (TELEGRAM_BOT_TOKEN not set)")

    return threads
