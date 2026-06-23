from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from uuid import uuid4

import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from src.gateway.file_message_pairing import (
    build_combined_file_message_content,
    looks_file_referential,
    looks_document_generation_request,
    should_generate_document_from_content,
)
from src.gateway.wecom_file_handler import summarize_file_bytes

logger = logging.getLogger(__name__)

DEFAULT_WS_URL = "wss://openws.work.weixin.qq.com"
_PAIR_TIMEOUT = 30.0
_TEXT_WAIT_SECONDS = 20.0
APP_CMD_UPLOAD_MEDIA_INIT = "aibot_upload_media_init"
APP_CMD_UPLOAD_MEDIA_CHUNK = "aibot_upload_media_chunk"
APP_CMD_UPLOAD_MEDIA_FINISH = "aibot_upload_media_finish"
APP_CMD_SEND = "aibot_send_msg"
APP_CMD_RESPONSE = "aibot_respond_msg"
UPLOAD_CHUNK_SIZE = 512 * 1024
REPLY_CONTEXT_TTL_SECONDS = 120.0
NON_RESPONSE_COMMANDS = {"aibot_msg_callback", "aibot_event_callback", "ping"}
MAX_INBOUND_FILE_BYTES = int(os.environ.get("ANT_COLONY_MAX_FILE_BYTES", str(50 * 1024 * 1024)))


def extract_bot_file_ref(body: dict[str, Any]) -> dict[str, str] | None:
    msgtype = str(body.get("msgtype") or "").lower()
    if msgtype == "file":
        file_info = body.get("file") if isinstance(body.get("file"), dict) else {}
        if not file_info:
            return None
        url = str(file_info.get("url") or "")
        return {
            "name": _normalize_filename(str(file_info.get("name") or ""), url),
            "url": url,
            "aeskey": str(file_info.get("aeskey") or ""),
            "base64": str(file_info.get("base64") or ""),
        }

    if msgtype == "appmsg":
        appmsg = body.get("appmsg") if isinstance(body.get("appmsg"), dict) else {}
        file_info = appmsg.get("file") if isinstance(appmsg.get("file"), dict) else {}
        if not file_info:
            return None
        url = str(file_info.get("url") or "")
        return {
            "name": _normalize_filename(str(file_info.get("name") or appmsg.get("title") or ""), url),
            "url": url,
            "aeskey": str(file_info.get("aeskey") or ""),
            "base64": str(file_info.get("base64") or ""),
        }
    return None


def build_gateway_payload_for_bot(body: dict[str, Any], msg_type: str, content: str) -> dict[str, Any]:
    chattype = str(body.get("chattype") or "single").lower()
    is_direct = chattype != "group"
    payload: dict[str, Any] = {
        "content": content,
        "from_user_id": body.get("from", {}).get("userid", ""),
        "msg_id": body.get("msgid", ""),
        "msg_type": msg_type,
        "created_at": int(time.time()),
        "is_direct": is_direct,
        "provider": "wecom_bot",
        "transport": "wecom_bot_ws",
    }
    if not is_direct:
        payload["space_id"] = body.get("chatid", "") or payload["from_user_id"]
    return payload


class WeComBotBridge:
    def __init__(self, gateway_url: str, bot_id: str, secret: str, ws_url: str = DEFAULT_WS_URL) -> None:
        self.gateway_url = gateway_url
        self.bot_id = bot_id
        self.secret = secret
        self.ws_url = ws_url
        self._running = False
        self._ws: Any = None
        self._heartbeat_task: asyncio.Task | None = None
        self._file_buffer: dict[str, tuple[str, float]] = {}
        self._text_buffer: dict[str, tuple[str, float]] = {}
        self._text_wait_tasks: dict[str, asyncio.Task] = {}
        self._last_req_by_chat: dict[str, tuple[str, float]] = {}
        self._device_id = uuid4().hex
        self._pending_acks: dict[str, asyncio.Future] = {}

    async def run_forever(self) -> None:
        try:
            import websockets
        except ImportError as exc:
            raise RuntimeError("websockets package is required for WeCom Bot bridge") from exc

        self._running = True
        retry_delay = 2.0
        while self._running:
            try:
                logger.info("Connecting WeCom Bot WebSocket: %s", self.ws_url)
                async with websockets.connect(self.ws_url, ping_interval=None, ping_timeout=None, close_timeout=5) as ws:
                    self._ws = ws
                    await self._subscribe()
                    retry_delay = 2.0
                    self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                    async for raw in ws:
                        await self._handle_ws_message(raw)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("WeCom Bot bridge disconnected: %s", exc)
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 60.0)
            finally:
                self._ws = None
                if self._heartbeat_task and not self._heartbeat_task.done():
                    self._heartbeat_task.cancel()
                self._heartbeat_task = None
                for task in self._text_wait_tasks.values():
                    if not task.done():
                        task.cancel()
                self._text_wait_tasks.clear()

    async def stop(self) -> None:
        self._running = False
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
        ws = self._ws
        if ws:
            await ws.close()

    async def _subscribe(self) -> None:
        assert self._ws is not None
        frame = {
            "cmd": "aibot_subscribe",
            "headers": {"req_id": str(uuid4())},
            "body": {
                "bot_id": self.bot_id,
                "secret": self.secret,
                "device_id": self._device_id,
            },
        }
        await self._ws.send(json.dumps(frame))
        raw = await asyncio.wait_for(self._ws.recv(), timeout=15)
        data = json.loads(raw)
        if data.get("errcode", -1) != 0:
            raise RuntimeError(f"WeCom Bot subscribe failed: {data}")

    async def _heartbeat_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(30)
                if not self._ws:
                    return
                await self._ws.send(json.dumps({"cmd": "ping", "headers": {"req_id": str(uuid4())}}))
        except asyncio.CancelledError:
            return

    async def _handle_ws_message(self, raw: str | bytes) -> None:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        data = json.loads(raw)
        cmd = data.get("cmd", "")
        req_id = data.get("headers", {}).get("req_id", "")
        if req_id and req_id in self._pending_acks and cmd not in NON_RESPONSE_COMMANDS:
            fut = self._pending_acks.get(req_id)
            if fut and not fut.done():
                fut.set_result(data)
            return
        if cmd == "aibot_msg_callback":
            asyncio.create_task(
                self._safe_handle_message_callback(
                    data.get("body", {}),
                    data.get("headers", {}).get("req_id", ""),
                )
            )
        elif cmd == "aibot_event_callback":
            logger.info("WeCom Bot event received: %s", data.get("body", {}).get("event", {}))

    async def _safe_handle_message_callback(self, body: dict[str, Any], req_id: str) -> None:
        try:
            await self._handle_message_callback(body, req_id=req_id)
        except Exception:
            logger.exception("WeCom Bot message handling failed")

    async def _handle_message_callback(self, body: dict[str, Any], req_id: str) -> None:
        now = time.time()
        self._clear_stale_buffers(now)

        user_id = body.get("from", {}).get("userid", "")
        chat_id = str(body.get("chatid") or user_id or "")
        if chat_id and req_id:
            self._last_req_by_chat[chat_id] = (req_id, now)

        msgtype = str(body.get("msgtype") or "").lower()
        file_ref = extract_bot_file_ref(body)
        logger.info(
            "WeCom Bot inbound: msgtype=%s user=%s chat=%s body_keys=%s file_ref=%s text_preview=%s",
            msgtype,
            user_id,
            chat_id,
            sorted(body.keys()),
            bool(file_ref),
            (self._extract_text(body)[:120] if not file_ref else file_ref),
        )
        if file_ref:
            summary = await self._summarize_file_ref(file_ref, user_id)
            recent_text = self._pop_recent_text(user_id, now)
            wait_task = self._text_wait_tasks.pop(user_id, None)
            if wait_task and not wait_task.done():
                wait_task.cancel()
            if recent_text:
                payload = build_gateway_payload_for_bot(
                    body,
                    "text",
                    build_combined_file_message_content(summary, recent_text),
                )
                payload["is_file_message"] = True
                await self._forward_to_gateway(payload, req_id=req_id, chat_id=chat_id)
            else:
                self._file_buffer[user_id] = (summary, now)
                await self._reply_text(req_id, f"已收到文件《{file_ref['name']}》。请继续发送你的要求，我会结合文件内容一起处理。")
            return

        content = self._extract_text(body)
        if not content:
            logger.info("WeCom Bot inbound ignored: empty extracted text for msgtype=%s body=%s", msgtype, body)
            return

        buffered_file = self._pop_recent_file(user_id, now)
        if buffered_file:
            content = build_combined_file_message_content(buffered_file, content)
            from_file = True
        elif looks_file_referential(content) or looks_document_generation_request(content):
            self._text_buffer[user_id] = (content, now)
            self._schedule_text_wait(user_id, body, req_id)
            return
        else:
            from_file = False

        payload = build_gateway_payload_for_bot(body, "text", content)
        if from_file:
            payload["is_file_message"] = True
        await self._forward_to_gateway(payload, req_id=req_id, chat_id=chat_id)

    async def _forward_to_gateway(self, payload: dict[str, Any], req_id: str = "", chat_id: str = "") -> None:
        logger.info(
            "Forwarding to gateway: req_id=%s chat=%s is_file=%s content_len=%s provider=%s",
            req_id,
            chat_id,
            payload.get("is_file_message"),
            len(str(payload.get("content") or "")),
            payload.get("provider"),
        )
        if payload.get("is_file_message") and should_generate_document_from_content(str(payload.get("content") or "")):
            await self._reply_text("", "已收到文件和要求，正在生成文档，请稍候 1-3 分钟。", chat_id=chat_id)
        timeout_seconds = 600 if payload.get("is_file_message") else 60
        async with httpx.AsyncClient(base_url=self.gateway_url, timeout=timeout_seconds) as client:
            resp = await client.post("/", json=payload)
            resp.raise_for_status()
            data = resp.json()
        logger.info("Gateway replied: req_id=%s keys=%s", req_id, sorted(data.keys()))
        reply = data.get("reply", "")
        if reply:
            if reply.startswith("[BOT_FILE]"):
                meta = json.loads(reply[len("[BOT_FILE]"):])
                await self._send_document(
                    req_id,
                    chat_id,
                    meta["path"],
                    meta.get("filename") or Path(meta["path"]).name,
                    meta.get("caption") or "",
                )
                return
            reply_req = req_id or self._reply_req_id_for_chat(chat_id)
            await self._reply_text(reply_req, reply, chat_id=chat_id)

    async def _reply_text(self, req_id: str, text: str, chat_id: str = "") -> None:
        if not self._ws or not text:
            return
        if req_id:
            await self._send_reply_request(
                req_id,
                {"msgtype": "markdown", "markdown": {"content": text[:4000]}},
            )
        else:
            await self._send_request(
                APP_CMD_SEND,
                {"chatid": chat_id, "msgtype": "markdown", "markdown": {"content": text[:4000]}},
            )

    async def _send_request(self, cmd: str, body: dict[str, Any], timeout: float = 30) -> dict[str, Any]:
        if not self._ws:
            raise RuntimeError("WeCom Bot websocket not connected")
        req_id = str(uuid4())
        fut = asyncio.get_running_loop().create_future()
        self._pending_acks[req_id] = fut
        try:
            frame = {"cmd": cmd, "headers": {"req_id": req_id}, "body": body}
            logger.info("WeCom Bot send request: cmd=%s req_id=%s timeout=%s", cmd, req_id, timeout)
            await self._ws.send(json.dumps(frame))
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._pending_acks.pop(req_id, None)

    async def _send_reply_request(self, reply_req_id: str, body: dict[str, Any], timeout: float = 60) -> dict[str, Any]:
        if not self._ws:
            raise RuntimeError("WeCom Bot websocket not connected")
        normalized_req_id = str(reply_req_id or "").strip()
        if not normalized_req_id:
            raise ValueError("reply_req_id is required")
        fut = asyncio.get_running_loop().create_future()
        self._pending_acks[normalized_req_id] = fut
        try:
            frame = {"cmd": "aibot_respond_msg", "headers": {"req_id": normalized_req_id}, "body": body}
            logger.info("WeCom Bot send reply: req_id=%s timeout=%s msgtype=%s", normalized_req_id, timeout, body.get("msgtype"))
            await self._ws.send(json.dumps(frame))
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._pending_acks.pop(normalized_req_id, None)

    async def _send_document(self, req_id: str, chat_id: str, file_path: str, filename: str, caption: str) -> None:
        data = Path(file_path).read_bytes()
        total_size = len(data)
        total_chunks = (total_size + UPLOAD_CHUNK_SIZE - 1) // UPLOAD_CHUNK_SIZE
        init_resp = await self._send_request(
            APP_CMD_UPLOAD_MEDIA_INIT,
            {
                "type": "file",
                "filename": filename,
                "total_size": total_size,
                "total_chunks": total_chunks,
                "md5": __import__("hashlib").md5(data).hexdigest(),
            },
            timeout=120,
        )
        upload_id = str((init_resp.get("body") or {}).get("upload_id") or "")
        if not upload_id:
            raise RuntimeError(f"missing upload_id in media init response: {init_resp}")
        logger.info("WeCom Bot media upload init ok: upload_id=%s chunks=%s size=%s", upload_id, total_chunks, total_size)
        for chunk_index, start in enumerate(range(0, total_size, UPLOAD_CHUNK_SIZE)):
            chunk = data[start:start + UPLOAD_CHUNK_SIZE]
            await self._send_request(
                APP_CMD_UPLOAD_MEDIA_CHUNK,
                {
                    "upload_id": upload_id,
                    "chunk_index": chunk_index,
                    "base64_data": base64.b64encode(chunk).decode("ascii"),
                },
                timeout=120,
            )
            logger.info("WeCom Bot media upload chunk ok: upload_id=%s chunk=%s/%s", upload_id, chunk_index + 1, total_chunks)
        finish_resp = await self._send_request(APP_CMD_UPLOAD_MEDIA_FINISH, {"upload_id": upload_id}, timeout=120)
        media_id = str((finish_resp.get("body") or {}).get("media_id") or "")
        if not media_id:
            raise RuntimeError(f"missing media_id in media finish response: {finish_resp}")
        logger.info("WeCom Bot media upload finish ok: media_id=%s", media_id)
        effective_req_id = req_id if self._is_reply_context_fresh(chat_id, req_id) else ""
        if effective_req_id:
            await self._send_reply_request(
                effective_req_id,
                {"msgtype": "file", "file": {"media_id": media_id}},
                timeout=60,
            )
        else:
            await self._send_request(
                APP_CMD_SEND,
                {
                    "chatid": chat_id,
                    "msgtype": "file",
                    "file": {"media_id": media_id},
                },
                timeout=60,
            )
        if caption:
            await self._reply_text(effective_req_id, caption, chat_id=chat_id)

    async def _summarize_file_ref(self, file_ref: dict[str, str], user_id: str) -> str:
        filename = _normalize_filename(file_ref.get("name") or "", file_ref.get("url", ""))
        if file_ref.get("base64"):
            raw = base64.b64decode(file_ref["base64"].split(",", 1)[-1])
            _ensure_file_size(raw, filename)
            return summarize_file_bytes(raw, filename, from_user_id=user_id)

        url = file_ref.get("url", "")
        if not url:
            return f"用户发送了文件：{filename}"
        parsed_url = urlparse(url)
        if parsed_url.scheme.lower() != "https" or not parsed_url.netloc:
            raise ValueError("WeCom Bot file URL must use HTTPS")
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=60) as resp:
            encrypted_overhead = 32 if file_ref.get("aeskey") else 0
            raw = resp.read(MAX_INBOUND_FILE_BYTES + encrypted_overhead + 1)
        aes_key = file_ref.get("aeskey", "")
        if aes_key:
            raw = _decrypt_file_bytes(raw, aes_key)
        _ensure_file_size(raw, filename)
        return summarize_file_bytes(raw, filename, from_user_id=user_id)

    @staticmethod
    def _extract_text(body: dict[str, Any]) -> str:
        msgtype = str(body.get("msgtype") or "").lower()
        if msgtype == "text":
            return str(body.get("text", {}).get("content") or "").strip()
        if msgtype == "voice":
            return str(body.get("voice", {}).get("content") or "").strip()
        if msgtype == "mixed":
            parts: list[str] = []
            for item in body.get("mixed", {}).get("msg_item", []) or []:
                if str(item.get("msgtype") or "").lower() == "text":
                    content = str(item.get("text", {}).get("content") or "").strip()
                    if content:
                        parts.append(content)
            return "\n".join(parts).strip()
        return ""

    def _clear_stale_buffers(self, now: float) -> None:
        for buffer_map in (self._file_buffer, self._text_buffer):
            stale = [key for key, (_, ts) in buffer_map.items() if now - ts > _PAIR_TIMEOUT]
            for key in stale:
                del buffer_map[key]
        finished = [key for key, task in self._text_wait_tasks.items() if task.done()]
        for key in finished:
            self._text_wait_tasks.pop(key, None)

    def _pop_recent_text(self, user_id: str, now: float) -> str | None:
        item = self._text_buffer.pop(user_id, None)
        if not item:
            return None
        text, ts = item
        return text if now - ts <= _PAIR_TIMEOUT else None

    def _pop_recent_file(self, user_id: str, now: float) -> str | None:
        item = self._file_buffer.pop(user_id, None)
        if not item:
            return None
        summary, ts = item
        return summary if now - ts <= _PAIR_TIMEOUT else None

    def _schedule_text_wait(self, user_id: str, body: dict[str, Any], req_id: str) -> None:
        existing = self._text_wait_tasks.get(user_id)
        if existing and not existing.done():
            existing.cancel()
        self._text_wait_tasks[user_id] = asyncio.create_task(self._flush_buffered_text_later(user_id, body, req_id))

    async def _flush_buffered_text_later(self, user_id: str, body: dict[str, Any], req_id: str) -> None:
        try:
            await asyncio.sleep(_TEXT_WAIT_SECONDS)
            item = self._text_buffer.pop(user_id, None)
            if not item:
                return
            text, ts = item
            if time.time() - ts > _PAIR_TIMEOUT:
                return
            payload = build_gateway_payload_for_bot(body, "text", text)
            await self._forward_to_gateway(payload, req_id=req_id, chat_id=str(body.get("chatid") or user_id or ""))
        except asyncio.CancelledError:
            return
        finally:
            task = self._text_wait_tasks.get(user_id)
            if task is asyncio.current_task():
                self._text_wait_tasks.pop(user_id, None)

    def _reply_req_id_for_chat(self, chat_id: str) -> str:
        entry = self._last_req_by_chat.get(chat_id)
        if not entry:
            return ""
        req_id, ts = entry
        if time.time() - ts > REPLY_CONTEXT_TTL_SECONDS:
            return ""
        return req_id

    def _is_reply_context_fresh(self, chat_id: str, req_id: str) -> bool:
        normalized = str(req_id or "").strip()
        if not normalized:
            return False
        entry = self._last_req_by_chat.get(chat_id)
        if not entry:
            return False
        cached_req_id, ts = entry
        return cached_req_id == normalized and (time.time() - ts) <= REPLY_CONTEXT_TTL_SECONDS


def _decrypt_file_bytes(data: bytes, aes_key: str) -> bytes:
    key = base64.b64decode(aes_key + "=" * (-len(aes_key) % 4))
    if len(key) != 32:
        raise ValueError("invalid aes key length")
    iv = key[:16]
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    decrypted = decryptor.update(data) + decryptor.finalize()
    pad_len = decrypted[-1]
    if pad_len < 1 or pad_len > 16:
        raise ValueError("invalid padding")
    return decrypted[:-pad_len]


def _normalize_filename(name: str, url: str) -> str:
    cleaned = (name or "").strip()
    if cleaned and cleaned.lower() != "document":
        return cleaned
    path_name = unquote(Path(urlparse(url).path).name) if url else ""
    return path_name or cleaned or "document"


def _ensure_file_size(data: bytes, filename: str) -> None:
    if len(data) > MAX_INBOUND_FILE_BYTES:
        raise ValueError(
            f"WeCom Bot file {filename!r} exceeds the {MAX_INBOUND_FILE_BYTES}-byte limit"
        )


async def run_wecom_bot_bridge() -> None:
    gateway_url = os.environ.get("WECOM_BOT_GATEWAY_URL", "http://127.0.0.1:18090")
    bot_id = os.environ.get("WECOM_BOT_ID", "").strip()
    secret = os.environ.get("WECOM_BOT_SECRET", "").strip()
    ws_url = os.environ.get("WECOM_WEBSOCKET_URL", DEFAULT_WS_URL).strip() or DEFAULT_WS_URL
    if not bot_id or not secret:
        raise RuntimeError("WECOM_BOT_ID and WECOM_BOT_SECRET are required")
    bridge = WeComBotBridge(gateway_url=gateway_url, bot_id=bot_id, secret=secret, ws_url=ws_url)
    await bridge.run_forever()
