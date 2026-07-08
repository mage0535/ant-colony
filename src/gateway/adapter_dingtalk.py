from __future__ import annotations

import hmac
import hashlib
import json
import logging
import os
import time
import urllib.request
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
from typing import Any

logger = logging.getLogger(__name__)

API_BASE = "https://oapi.dingtalk.com"
DEFAULT_PORT = 18766
DEDUP_WINDOW = 300.0
DEDUP_MAX_ENTRIES = 1000
MAX_RETRIES = 5
BASE_DELAY = 1.0
MAX_DELAY = 60.0
MSG_TTL = 3600.0

__all__ = ["DingTalkAdapter", "serve"]


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


class MessageDeduper:
    __slots__ = ("_window", "_max", "_entries")

    def __init__(self, window: float = DEDUP_WINDOW, max_entries: int = DEDUP_MAX_ENTRIES) -> None:
        self._window = window
        self._max = max_entries
        self._entries: OrderedDict[str, float] = OrderedDict()

    def seen(self, message_id: str) -> bool:
        now = time.time()
        self._evict(now)
        if message_id in self._entries:
            return True
        self._entries[message_id] = now
        self._trim()
        return False

    def _evict(self, now: float) -> None:
        cutoff = now - self._window
        while self._entries:
            _, ts = next(iter(self._entries.items()))
            if ts >= cutoff:
                break
            self._entries.popitem(last=False)

    def _trim(self) -> None:
        while len(self._entries) > self._max:
            self._entries.popitem(last=False)


class TokenManager:
    def __init__(self, app_key: str, app_secret: str) -> None:
        self._app_key = app_key
        self._app_secret = app_secret
        self._cache: tuple[str, float] = ("", 0.0)

    def get_token(self) -> str:
        token, expires = self._cache
        if token and time.time() < expires - 60:
            return token
        url = f"{API_BASE}/gettoken?appkey={self._app_key}&appsecret={self._app_secret}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        if data.get("errcode", 0) != 0:
            raise RuntimeError(f"DingTalk token error: {data.get('errmsg', 'unknown')}")
        self._cache = (data["access_token"], time.time() + data.get("expires_in", 7200))
        return self._cache[0]


def _hmac_sha256(key: str, content: str) -> str:
    return hmac.new(key.encode("utf-8"), content.encode("utf-8"), hashlib.sha256).hexdigest()


class DingTalkAdapter:
    def __init__(self, gateway_url: str = "http://localhost:18090/webhook") -> None:
        self.gateway_url = gateway_url
        self._client_id = _env("DINGTALK_CLIENT_ID", "")
        self._client_secret = _env("DINGTALK_CLIENT_SECRET", "")
        self._allowed_users_raw = _env("DINGTALK_ALLOWED_USERS", "*")

        self._allowed_users: set[str] | None = None if self._allowed_users_raw == "*" else set(
            u.strip() for u in self._allowed_users_raw.split(",") if u.strip()
        )

        self._deduper = MessageDeduper()
        self._token_mgr = TokenManager(self._client_id, self._client_secret)
        self._server: ThreadingHTTPServer | None = None
        self._thread: Thread | None = None
        self._stop_event = Event()

    def start(self, host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> None:
        handler = _make_handler(self)
        self._server = ThreadingHTTPServer((host, port), handler)
        self._thread = Thread(target=self._server.serve_forever, daemon=True, name="dingtalk-webhook")
        self._thread.start()
        logger.info("DingTalk webhook listening on %s:%s", host, port)

    def stop(self) -> None:
        self._stop_event.set()
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)
        logger.info("DingTalk adapter stopped")

    def _ensure_token(self) -> str:
        return self._token_mgr.get_token()

    def send_message(self, chat_id: str, text: str, title: str = "AI 助手") -> bool:
        if not chat_id or not text:
            return False
        try:
            token = self._ensure_token()
            msg_param = json.dumps({"title": title, "text": text}, ensure_ascii=False)
            payload = json.dumps({
                "targetId": chat_id,
                "msgKey": "sampleMarkdown",
                "msgParam": msg_param,
            }, ensure_ascii=False).encode("utf-8")

            url = f"{API_BASE}/topapi/im/chat/scencegroup/message/send_v2?access_token={token}"
            req = urllib.request.Request(url, data=payload, headers={
                "Content-Type": "application/json; charset=utf-8",
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

            if data.get("errcode", 0) != 0:
                logger.warning("DingTalk send failed: %s (code=%s)", data.get("errmsg", "unknown"), data.get("errcode"))
                return False

            logger.info("DingTalk message sent to chat %s (%d chars)", chat_id, len(text))
            return True
        except Exception as e:
            logger.error("DingTalk send error: %s", e)
            return False

    def _handle_event(self, body: dict[str, Any], raw_body: str) -> dict[str, Any] | None:
        # Handle DingTalk callback event validation
        if body.get("msgtype") == "url_verify":
            return {"msg": "ok"}

        # Parse DingTalk event format
        # DingTalk robot webhook events come as: {"conversationId": "...", "atUsers": [...], "chatbotUserId": "...", "isInAtList": ..., "msgtype": "text", "text": {"content": "..."}, "senderId": "...", "conversationTitle": "...", "senderNick": "...", "sessionWebhook": "", "senderStaffId": "...", "createAt": ...}
        conversation_type = body.get("conversationType", "")
        conversation_id = body.get("conversationId", "")
        sender_id = body.get("senderStaffId", "") or body.get("senderId", "") or body.get("senderUserId", "")
        msgtype = body.get("msgtype", "")
        if msgtype == "text":
            text = body.get("text", {}).get("content", "") if isinstance(body.get("text"), dict) else ""
        elif msgtype == "file":
            file_info = body.get("file", {}) if isinstance(body.get("file"), dict) else {}
            filename = file_info.get("fileName", "") or file_info.get("file_name", "")
            text = f"用户发送了文件：{filename or '未命名文件'}"
        else:
            logger.debug("Ignoring unsupported message type: %s", msgtype)
            return None

        msg_id = body.get("msgId", "") or str(body.get("createAt", ""))
        if self._deduper.seen(msg_id):
            logger.debug("Deduped message %s", msg_id)
            return None

        if not sender_id or not text:
            logger.warning("Missing sender_id or text in DingTalk event")
            return None

        if conversation_type == "group":
            at_users = body.get("atUsers", [])
            if not at_users:
                logger.debug("Ignoring group message without @mention")
                return None

        if self._allowed_users is not None and sender_id not in self._allowed_users:
            logger.info("Ignoring message from disallowed user: %s", sender_id)
            return None

        reply = self._forward_to_gateway(sender_id, text, conversation_id, conversation_type)

        if reply:
            self.send_message(conversation_id, reply)

        return None

    def _forward_to_gateway(self, user_id: str, text: str, chat_id: str, chat_type: str) -> str:
        payload = json.dumps({
            "from": user_id,
            "text": text,
            "platform": "dingtalk",
            "source_chat_id": chat_id,
            "chat_type": chat_type,
        }).encode("utf-8")

        reply = ""
        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                req = urllib.request.Request(
                    self.gateway_url,
                    data=payload,
                    headers={"Content-Type": "application/json; charset=utf-8"},
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    result = json.loads(resp.read())
                reply = result.get("reply", "") or result.get("text", "")
                break
            except Exception as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)
                    logger.warning(
                        "Gateway forward attempt %d/%d failed, retry in %.1fs: %s",
                        attempt + 1, MAX_RETRIES, delay, e,
                    )
                    time.sleep(delay)

        if last_error and not reply:
            logger.error("Gateway forwarding failed after %d attempts: %s", MAX_RETRIES, last_error)

        return reply


def _make_handler(adapter: DingTalkAdapter) -> type[BaseHTTPRequestHandler]:
    class _DingTalkWebhookHandler(BaseHTTPRequestHandler):
        _adapter = adapter

        def log_message(self, fmt: str, *args: Any) -> None:
            logger.debug("dingtalk-webhook: %s", fmt % args)

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            body_str = raw.decode("utf-8")

            try:
                payload: dict[str, Any] = json.loads(body_str)
            except json.JSONDecodeError as e:
                self._respond(400, {"error": f"bad json: {e}"})
                return

            try:
                result = self._adapter._handle_event(payload, body_str)
                if result is not None:
                    self._respond(200, result)
                else:
                    self._respond(200, {})
            except Exception as e:
                logger.exception("DingTalk event handler error")
                self._respond(500, {"error": str(e)})

        def do_GET(self) -> None:
            self._respond(200, {"status": "ok", "service": "dingtalk-adapter"})

        def _respond(self, code: int, data: Any) -> None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return _DingTalkWebhookHandler


def serve(gateway_url: str = "http://localhost:18090/webhook",
          host: str = "0.0.0.0",
          port: int = DEFAULT_PORT) -> DingTalkAdapter:
    adapter = DingTalkAdapter(gateway_url=gateway_url)
    adapter.start(host=host, port=port)
    return adapter


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    adapter = serve()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        adapter.stop()
