import os
import json
import time
import logging
import threading
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode

logger = logging.getLogger(__name__)


class TelegramAdapter:
    POLL_INTERVAL = 1.0
    POLL_TIMEOUT = 30
    DEDUP_WINDOW = 300
    DEDUP_MAX = 1000
    MAX_RETRIES = 3

    def __init__(self, gateway_url="http://localhost:18090/webhook"):
        self.gateway_url = gateway_url
        self.token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        allowed_raw = os.environ.get("TELEGRAM_ALLOWED_USERS", "")
        self.allowed_users = set()
        for part in allowed_raw.split(","):
            part = part.strip()
            if part:
                self.allowed_users.add(part)
        self.home_channel = os.environ.get("TELEGRAM_HOME_CHANNEL", "")
        self.bot_user = None
        self.bot_name = None
        self._running = False
        self._poll_thread = None
        self._last_update_id = 0
        self._dedup_keys = []
        self._dedup_set = set()
        self._lock = threading.Lock()

    @property
    def _api_base(self):
        return f"https://api.telegram.org/bot{self.token}"

    def _request(self, method, endpoint, data=None):
        url = f"{self._api_base}/{endpoint}"
        body = json.dumps(data).encode("utf-8") if data else None
        req = Request(url, data=body, method=method)
        req.add_header("Content-Type", "application/json")
        for attempt in range(self.MAX_RETRIES):
            try:
                with urlopen(req, timeout=60) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except (URLError, HTTPError, OSError, json.JSONDecodeError) as exc:
                logger.warning("Telegram API error (attempt %d/%d): %s", attempt + 1, self.MAX_RETRIES, exc)
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(1.0 * (2 ** attempt))
        return None

    def _dedup_check(self, key):
        now = time.time()
        with self._lock:
            if key in self._dedup_set:
                return True
            self._dedup_set.add(key)
            self._dedup_keys.append((key, now))
            cutoff = now - self.DEDUP_WINDOW
            while self._dedup_keys and self._dedup_keys[0][1] < cutoff:
                old_key, _ = self._dedup_keys.pop(0)
                self._dedup_set.discard(old_key)
            if len(self._dedup_keys) > self.DEDUP_MAX:
                old_key, _ = self._dedup_keys.pop(0)
                self._dedup_set.discard(old_key)
        return False

    def _get_me(self):
        result = self._request("GET", "getMe")
        if result and result.get("ok"):
            user = result["result"]
            self.bot_user = user
            self.bot_name = user.get("username", "")
            logger.info("Bot authenticated as @%s (id=%s)", self.bot_name, user.get("id"))

    def _is_group(self, chat):
        return chat.get("type") in ("group", "supergroup")

    def _should_respond(self, msg, chat):
        if not self._is_group(chat):
            return True
        text = msg.get("text", "") or msg.get("caption", "") or ""
        if text.startswith("/"):
            return True
        if self.bot_name and f"@{self.bot_name}" in text:
            return True
        reply = msg.get("reply_to_message")
        if reply:
            fr = reply.get("from", {})
            if fr.get("id") == (self.bot_user or {}).get("id"):
                return True
        return False

    def _forward_to_gateway(self, user_id, text, chat_id, msg_id):
        payload = {
            "from": str(user_id),
            "text": text,
            "platform": "telegram",
            "chat_id": str(chat_id),
            "message_id": msg_id,
        }
        try:
            body = json.dumps(payload).encode("utf-8")
            req = Request(self.gateway_url, data=body, method="POST")
            req.add_header("Content-Type", "application/json")
            with urlopen(req, timeout=30) as resp:
                reply_data = json.loads(resp.read().decode("utf-8"))
            reply_text = None
            if isinstance(reply_data, dict):
                reply_text = reply_data.get("reply") or reply_data.get("text") or reply_data.get("response")
            elif isinstance(reply_data, str):
                reply_text = reply_data
            if reply_text:
                self.send_message(chat_id, reply_text)
        except Exception as exc:
            logger.error("Gateway forward failed: %s", exc)

    def _process_message(self, msg):
        chat = msg.get("chat")
        if not chat:
            return
        chat_id = chat.get("id")
        user_id = msg.get("from", {}).get("id")
        if not user_id or not chat_id:
            return
        uid_str = str(user_id)
        if self.allowed_users and uid_str not in self.allowed_users:
            return
        dedup_key = f"{chat_id}:{msg.get('message_id', '')}"
        if self._dedup_check(dedup_key):
            return
        if not self._should_respond(msg, chat):
            return
        text = msg.get("text", "") or msg.get("caption", "") or ""
        voice = msg.get("voice")
        if voice:
            text = text or self._handle_voice(voice)
        document = msg.get("document")
        if document:
            self._handle_document(document, chat_id, msg.get("message_id"))
        if text:
            self._forward_to_gateway(user_id, text, chat_id, msg.get("message_id"))

    def _handle_voice(self, voice):
        file_id = voice.get("file_id")
        if not file_id:
            logger.warning("Voice message without file_id")
            return ""
        file_path = self._get_file_path(file_id)
        if not file_path:
            return ""
        file_url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
        try:
            with urlopen(file_url, timeout=30) as resp:
                ogg_data = resp.read()
            return f"[voice:{file_id}]"
        except Exception as exc:
            logger.error("Failed to download voice file: %s", exc)
            return ""

    def _handle_document(self, document, chat_id, msg_id):
        file_id = document.get("file_id")
        if not file_id:
            return
        file_path = self._get_file_path(file_id)
        if not file_path:
            return
        file_url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
        file_name = document.get("file_name", f"file_{file_id}")
        try:
            with urlopen(file_url, timeout=60) as resp:
                file_data = resp.read()
            logger.info("Downloaded document %s (%d bytes)", file_name, len(file_data))
        except Exception as exc:
            logger.error("Failed to download document %s: %s", file_name, exc)

    def _get_file_path(self, file_id):
        result = self._request("GET", f"getFile?file_id={file_id}")
        if result and result.get("ok"):
            return result["result"].get("file_path")
        return None

    def _poll(self):
        logger.info("Polling started (offset=%s)", self._last_update_id)
        while self._running:
            try:
                params = {
                    "offset": self._last_update_id + 1,
                    "timeout": self.POLL_TIMEOUT,
                }
                result = self._request("GET", f"getUpdates?{urlencode(params)}")
                if result and result.get("ok"):
                    for update in result.get("result", []):
                        self._last_update_id = update.get("update_id", self._last_update_id)
                        msg = update.get("message")
                        if msg:
                            self._process_message(msg)
                else:
                    time.sleep(self.POLL_INTERVAL)
            except Exception as exc:
                logger.error("Poll error: %s", exc)
                time.sleep(self.POLL_INTERVAL)

    def start(self):
        if self._running:
            logger.warning("Already running")
            return
        if not self.token:
            raise ValueError("TELEGRAM_BOT_TOKEN is not set")
        self._get_me()
        if not self.bot_user:
            raise RuntimeError("Failed to authenticate bot")
        self._running = True
        self._poll_thread = threading.Thread(target=self._poll, daemon=True, name="telegram-poll")
        self._poll_thread.start()
        logger.info("TelegramAdapter started")

    def stop(self):
        logger.info("Stopping TelegramAdapter...")
        self._running = False
        if self._poll_thread:
            self._poll_thread.join(timeout=5)
        logger.info("TelegramAdapter stopped")

    def send_message(self, chat_id, text, parse_mode=None, reply_to_message_id=None):
        if not text:
            return
        data = {
            "chat_id": chat_id,
            "text": text,
        }
        if parse_mode:
            data["parse_mode"] = parse_mode
        if reply_to_message_id:
            data["reply_to_message_id"] = reply_to_message_id
        result = self._request("GET", f"sendMessage?{urlencode(data)}")
        if result and result.get("ok"):
            return result["result"]
        return None

    def send_home_message(self, text, parse_mode=None):
        if not self.home_channel:
            logger.warning("TELEGRAM_HOME_CHANNEL not configured, cannot send home message")
            return
        self.send_message(self.home_channel, text, parse_mode=parse_mode)
