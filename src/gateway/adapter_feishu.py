from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
from typing import Any
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

FEISHU_DOMAINS = {
    "cn": "https://open.feishu.cn",
    "feishu": "https://open.feishu.cn",
    "lark": "https://open.larksuite.com",
    "intl": "https://open.larksuite.com",
}

DEFAULT_PORT = 18765
DEDUP_WINDOW = 300.0
DEDUP_MAX_ENTRIES = 1000
MAX_RETRIES = 5
BASE_DELAY = 1.0
MAX_DELAY = 60.0


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _feishu_domain() -> str:
    key = _env("FEISHU_DOMAIN", "cn").lower()
    return FEISHU_DOMAINS.get(key, FEISHU_DOMAINS["cn"])


def _verify_signature(app_secret: str, timestamp: str, nonce: str, body: str, signature: str) -> bool:
    if not app_secret:
        logger.warning("FEISHU_APP_SECRET not set, skipping signature verification")
        return True
    raw = timestamp + nonce + body
    expected = base64.b64encode(
        hmac.new(app_secret.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).digest()
    ).decode("utf-8")
    return hmac.compare_digest(expected, signature)


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


class FeishuAdapter:
    def __init__(self, gateway_url: str = "http://localhost:18090/webhook") -> None:
        self.gateway_url = gateway_url
        self._app_id = _env("FEISHU_APP_ID", "")
        self._app_secret = _env("FEISHU_APP_SECRET", "")
        self._allowed_users_raw = _env("FEISHU_ALLOWED_USERS", "*")
        self._home_chat_id = _env("FEISHU_HOME_CHANNEL", "")

        self._domain = _feishu_domain()
        self._allowed_users: set[str] | None = None if self._allowed_users_raw == "*" else set(
            u.strip() for u in self._allowed_users_raw.split(",") if u.strip()
        )

        self._deduper = MessageDeduper()
        self._server: ThreadingHTTPServer | None = None
        self._thread: Thread | None = None
        self._stop_event = Event()
        self._token_cache: tuple[str, float] = ("", 0.0)

    def start(self, host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> None:
        handler = _make_handler(self)
        self._server = ThreadingHTTPServer((host, port), handler)
        self._thread = Thread(target=self._server.serve_forever, daemon=True, name="feishu-webhook")
        self._thread.start()
        logger.info("Feishu webhook listening on %s:%s", host, port)

    def stop(self) -> None:
        self._stop_event.set()
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)
        logger.info("Feishu adapter stopped")

    def send_message(self, chat_id: str, text: str, msg_type: str = "text") -> bool:
        if not chat_id or not text:
            return False
        try:
            token = self._get_tenant_token()
            if not token:
                logger.error("Cannot send: no tenant token")
                return False

            content = json.dumps({"text": text}, ensure_ascii=False)
            url = f"{self._domain}/open-apis/im/v1/messages?receive_id_type=chat_id"
            payload = json.dumps({
                "receive_id": chat_id,
                "msg_type": msg_type,
                "content": content,
            }, ensure_ascii=False).encode("utf-8")

            req = Request(url, data=payload, headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
            })
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

            if data.get("code", 0) != 0:
                logger.warning("Feishu send failed: %s (code=%s)", data.get("msg", "unknown"), data.get("code"))
                return False

            logger.info("Feishu message sent to chat %s (%d chars)", chat_id, len(text))
            return True
        except Exception as e:
            logger.error("Feishu send error: %s", e)
            return False

    def send_home_notification(self, text: str) -> bool:
        if not self._home_chat_id:
            logger.warning("FEISHU_HOME_CHANNEL not configured")
            return False
        return self.send_message(self._home_chat_id, text)

    def _get_tenant_token(self) -> str:
        token, expires = self._token_cache
        if token and time.time() < expires - 60:
            return token

        url = f"{self._domain}/open-apis/auth/v3/tenant_access_token/internal"
        payload = json.dumps({
            "app_id": self._app_id,
            "app_secret": self._app_secret,
        }).encode("utf-8")

        req = Request(url, data=payload, headers={"Content-Type": "application/json; charset=utf-8"})
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

        if data.get("code", 0) != 0:
            raise RuntimeError(f"Feishu tenant token error: {data.get('msg', 'unknown')}")

        self._token_cache = (data["tenant_access_token"], time.time() + data.get("expire", 7200))
        return self._token_cache[0]

    def _handle_event(self, body: dict[str, Any], raw_body: str) -> dict[str, Any] | None:
        if body.get("type") == "url_verify":
            challenge = body.get("challenge", "")
            logger.info("Feishu URL verification challenge processed")
            return {"challenge": challenge}

        header = body.get("header", {})
        event_type = header.get("event_type", "")
        if event_type != "im.message.receive_v1":
            return None

        event = body.get("event", {})
        message = event.get("message", {})
        sender = event.get("sender", {})

        message_id = message.get("message_id", "")
        if self._deduper.seen(message_id):
            logger.debug("Deduped message %s", message_id)
            return None

        message_type = message.get("message_type", "")
        if message_type != "text":
            logger.debug("Ignoring non-text message type: %s", message_type)
            return None

        chat_type = message.get("chat_type", "")
        chat_id = message.get("chat_id", "")
        sender_id_info = sender.get("sender_id", {})
        user_id = sender_id_info.get("user_id", "") or sender_id_info.get("open_id", "")

        if not user_id or not chat_id:
            logger.warning("Missing user_id or chat_id in Feishu event")
            return None

        try:
            content_obj = json.loads(message.get("content", "{}"))
            text = content_obj.get("text", "")
        except (json.JSONDecodeError, TypeError):
            text = ""

        if not text:
            return None

        if chat_type == "group":
            mentions = message.get("mentions", [])
            if not mentions:
                logger.debug("Ignoring group message without @mention")
                return None

        if self._allowed_users is not None and user_id not in self._allowed_users:
            logger.info("Ignoring message from disallowed user: %s", user_id)
            return None

        reply = self._forward_to_gateway(user_id, text, chat_id, chat_type)

        if reply:
            target_chat = chat_id
            self.send_message(target_chat, reply)

        return None

    def _forward_to_gateway(self, user_id: str, text: str, chat_id: str, chat_type: str) -> str:
        payload = json.dumps({
            "from": user_id,
            "text": text,
            "platform": "feishu",
            "source_chat_id": chat_id,
            "chat_type": chat_type,
        }).encode("utf-8")

        reply = ""
        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                req = Request(
                    self.gateway_url,
                    data=payload,
                    headers={"Content-Type": "application/json; charset=utf-8"},
                )
                with urlopen(req, timeout=15) as resp:
                    result = json.loads(resp.read())
                reply = result.get("reply", "") or result.get("text", "")
                break
            except Exception as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    delay = min(BASE_DELAY * (2**attempt), MAX_DELAY)
                    logger.warning(
                        "Gateway forward attempt %d/%d failed, retry in %.1fs: %s",
                        attempt + 1, MAX_RETRIES, delay, e,
                    )
                    time.sleep(delay)

        if last_error and not reply:
            logger.error("Gateway forwarding failed after %d attempts: %s", MAX_RETRIES, last_error)

        return reply


def _make_handler(adapter: FeishuAdapter) -> type[BaseHTTPRequestHandler]:
    class _FeishuWebhookHandler(BaseHTTPRequestHandler):
        _adapter = adapter

        def log_message(self, fmt: str, *args: Any) -> None:
            logger.debug("feishu-webhook: %s", fmt % args)

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)

            timestamp = self.headers.get("X-Lark-Request-Timestamp", "")
            nonce = self.headers.get("X-Lark-Request-Nonce", "")
            signature = self.headers.get("X-Lark-Signature", "")
            body_str = raw.decode("utf-8")

            if timestamp and nonce and signature:
                if not _verify_signature(self._adapter._app_secret, timestamp, nonce, body_str, signature):
                    logger.warning("Invalid Feishu signature")
                    self._respond(403, {"error": "invalid signature"})
                    return

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
                logger.exception("Feishu event handler error")
                self._respond(500, {"error": str(e)})

        def do_GET(self) -> None:
            self._respond(200, {"status": "ok", "service": "feishu-adapter"})

        def _respond(self, code: int, data: Any) -> None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return _FeishuWebhookHandler


def serve(gateway_url: str = "http://localhost:18090/webhook",
          host: str = "0.0.0.0",
          port: int = DEFAULT_PORT) -> FeishuAdapter:
    adapter = FeishuAdapter(gateway_url=gateway_url)
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
