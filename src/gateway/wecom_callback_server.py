from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import random
import socket
import string
import struct
import time
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import urlparse, parse_qs
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

logger = logging.getLogger(__name__)


class WeComCrypto:
    """Enterprise WeChat callback crypto (AES-256-CBC + SHA1 signature)."""

    def __init__(self, token: str, encoding_aes_key: str, corp_id: str) -> None:
        self.token = token
        self.corp_id = corp_id
        self.aes_key = base64.b64decode(encoding_aes_key + "=")

    def verify_signature(self, signature: str, timestamp: str, nonce: str, echostr: str = "") -> bool:
        items = sorted([self.token, timestamp, nonce, echostr])
        sha1 = hashlib.sha1("".join(items).encode()).hexdigest()
        return sha1 == signature

    def decrypt(self, encrypted: str) -> str:
        cipher_text = base64.b64decode(encrypted)
        iv = self.aes_key[:16]
        cipher = Cipher(algorithms.AES(self.aes_key), modes.CBC(iv))
        decryptor = cipher.decryptor()
        decrypted = decryptor.update(cipher_text) + decryptor.finalize()
        pad_len = decrypted[-1]
        content = decrypted[:-pad_len]
        msg_len = struct.unpack("!I", content[16:20])[0]
        msg = content[20:20 + msg_len].decode("utf-8")
        from_corp = content[20 + msg_len:].decode("utf-8")
        if from_corp != self.corp_id:
            raise ValueError(f"corp_id mismatch: {from_corp}")
        return msg

    def encrypt(self, reply_msg: str) -> str:
        msg_bytes = reply_msg.encode("utf-8")
        rand = "".join(random.choices(string.ascii_letters + string.digits, k=16)).encode()
        content = rand + struct.pack("!I", len(msg_bytes)) + msg_bytes + self.corp_id.encode()
        pad_len = 32 - (len(content) % 32)
        content += bytes([pad_len] * pad_len)
        iv = self.aes_key[:16]
        cipher = Cipher(algorithms.AES(self.aes_key), modes.CBC(iv))
        encryptor = cipher.encryptor()
        return base64.b64encode(encryptor.update(content) + encryptor.finalize()).decode()

    def generate_signature(self, encrypted: str, timestamp: str, nonce: str) -> str:
        items = sorted([self.token, timestamp, nonce, encrypted])
        return hashlib.sha1("".join(items).encode()).hexdigest()

    def decrypt_callback(self, xml_text: str, msg_signature: str, timestamp: str, nonce: str) -> dict[str, str]:
        root = ET.fromstring(xml_text)
        encrypt_node = root.find("Encrypt")
        if encrypt_node is None or encrypt_node.text is None:
            raise ValueError("missing Encrypt node")
        encrypted = encrypt_node.text
        if not self.verify_signature(msg_signature, timestamp, nonce, encrypted):
            raise ValueError("signature verification failed")
        decrypted_xml = self.decrypt(encrypted)
        msg_root = ET.fromstring(decrypted_xml)
        return {child.tag: child.text or "" for child in msg_root}

    def encrypt_reply(self, reply_xml: str) -> str:
        encrypted = self.encrypt(reply_xml)
        ts = str(int(time.time()))
        nonce = "".join(random.choices(string.digits, k=10))
        sig = self.generate_signature(encrypted, ts, nonce)
        return f"""<xml>
<Encrypt><![CDATA[{encrypted}]]></Encrypt>
<MsgSignature><![CDATA[{sig}]]></MsgSignature>
<TimeStamp>{ts}</TimeStamp>
<Nonce><![CDATA[{nonce}]]></Nonce>
</xml>"""


class CallbackHandler(BaseHTTPRequestHandler):
    crypto: WeComCrypto | None = None
    gateway_url: str = "http://127.0.0.1:18090"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if self.crypto is None:
            self._respond_text(503, "crypto not initialized")
            return
        try:
            msg_sig = params.get("msg_signature", [""])[0]
            ts = params.get("timestamp", [""])[0]
            nonce = params.get("nonce", [""])[0]
            echostr = params.get("echostr", [""])[0]
            if self.crypto.verify_signature(msg_sig, ts, nonce, echostr):
                decrypted = self.crypto.decrypt(echostr)
                self._respond_text(200, decrypted)
            else:
                self._respond_text(403, "verification failed")
        except Exception as e:
            logger.exception("GET /callback/wecom error")
            self._respond_text(500, str(e))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if self.crypto is None:
            self._respond_text(503, "crypto not initialized")
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            msg_sig = params.get("msg_signature", [""])[0]
            ts = params.get("timestamp", [""])[0]
            nonce = params.get("nonce", [""])[0]
            msg_dict = self.crypto.decrypt_callback(raw.decode(), msg_sig, ts, nonce)
            # Respond 200 immediately to prevent WeCom retries,
            # then process asynchronously in background thread
            self._respond_text(200, "success")
            import threading
            t = threading.Thread(target=self._forward_and_reply, args=(msg_dict,), daemon=True)
            t.start()
        except Exception as e:
            logger.exception("POST /callback/wecom error")
            try:
                self._respond_text(500, str(e))
            except Exception:
                pass

    def _forward_and_reply(self, msg_dict: dict[str, str]) -> str | None:
        import httpx
        from src.gateway.wecom_outbound import send_text
        msg_type = msg_dict.get("MsgType", "text")
        payload: dict[str, Any] = {
            "content": msg_dict.get("Content", ""),
            "from_user_id": msg_dict.get("FromUserName", ""),
            "msg_id": msg_dict.get("MsgId", ""),
            "msg_type": msg_type,
            "created_at": int(time.time()),
        }
        if msg_type == "file":
            payload["media_id"] = msg_dict.get("MediaId", "")
            payload["file_key"] = msg_dict.get("FileKey", "")
            payload["file_size"] = msg_dict.get("FileSize", "0")
            payload["file_md5"] = msg_dict.get("Md5", "")
        conversation_type = msg_dict.get("ConversationType", "")
        if conversation_type == "group":
            payload["space_id"] = msg_dict.get("ChatId") or msg_dict.get("FromUserName", "")
            payload["is_direct"] = False
        else:
            payload["is_direct"] = True
        try:
            with httpx.Client(base_url=self.gateway_url, timeout=60) as client:
                resp = client.post("/", json=payload)
                if resp.status_code != 200:
                    logger.warning("gateway returned %s: %s", resp.status_code, resp.text[:200])
                    return None
                data = resp.json()
                reply = data.get("reply", "")
                if reply and payload.get("is_direct"):
                    user_id = payload["from_user_id"]
                    send_text(user_id, reply)
                    logger.info("Agent replied to %s (%d chars)", user_id, len(reply))
                    return reply  # Return for WeCom pass-through if needed
                return None
        except Exception as e:
            logger.error("Failed to forward to gateway: %s", e)
            return None

    def _respond_text(self, code: int, text: str) -> None:
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.info("wecom-callback: %s", fmt % args)


def load_crypto_from_env(prefix: str = "WECOM_") -> WeComCrypto | None:
    token = os.environ.get(f"{prefix}CALLBACK_TOKEN", "")
    aes_key = os.environ.get(f"{prefix}CALLBACK_AES_KEY", "")
    corp_id = os.environ.get(f"{prefix}CORP_ID", "")
    if not (token and aes_key and corp_id):
        return None
    return WeComCrypto(token, aes_key, corp_id)


def serve(host: str = "0.0.0.0", port: int = 18091) -> None:
    crypto = load_crypto_from_env()
    if crypto:
        logger.info("WeCom crypto configured for corp_id=%s", crypto.corp_id)
    else:
        logger.warning("WeCom crypto not configured (set WECOM_CALLBACK_TOKEN/AES_KEY/CORP_ID env vars)")

    class DynamicHandler(CallbackHandler):
        pass
    DynamicHandler.crypto = crypto
    DynamicHandler.gateway_url = f"http://127.0.0.1:18090"

    server = HTTPServer((host, port), DynamicHandler)
    logger.info("WeCom callback server listening on %s:%s", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
        logger.info("WeCom callback server stopped")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    serve()
