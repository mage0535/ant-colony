from __future__ import annotations

import json
import logging
import mimetypes
import os
import re
import time
import urllib.request
from urllib.parse import unquote

logger = logging.getLogger(__name__)

WECOM_API = "https://qyapi.weixin.qq.com/cgi-bin"
_ENV_FILE_CANDIDATES = [
    os.path.join(os.getcwd(), "infra", ".env.wecom"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "infra", ".env.wecom"),
    os.path.join(os.environ.get("ANT_COLONY_HOME", ""), "infra", ".env.wecom") if os.environ.get("ANT_COLONY_HOME") else "",
    os.path.expanduser("~/ant-colony/infra/.env.wecom"),
]


def _load_env_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for env_file in _ENV_FILE_CANDIDATES:
        if not os.path.isfile(env_file):
            continue
        with open(env_file, encoding="utf-8", errors="replace") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
        break
    for key in ("WECOM_CORP_ID", "WECOM_AGENT_ID", "WECOM_SECRET"):
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values


_ENV = _load_env_values()
CORP_ID = _ENV.get("WECOM_CORP_ID", "")
AGENT_ID = int(_ENV.get("WECOM_AGENT_ID", "1000006"))
APP_SECRET = _ENV.get("WECOM_SECRET", "")

_token_cache: tuple[str, float] = ("", 0)


def _get_token() -> str:
    global _token_cache
    token, expires = _token_cache
    if token and time.time() < expires - 60:
        return token
    url = f"{WECOM_API}/gettoken?corpid={CORP_ID}&corpsecret={APP_SECRET}"
    with urllib.request.urlopen(urllib.request.Request(url), timeout=10) as resp:
        data = json.loads(resp.read())
    if data.get("errcode", 0) != 0:
        raise RuntimeError(f"WeCom token error: {data.get('errmsg')}")
    _token_cache = (data["access_token"], time.time() + data.get("expires_in", 7200))
    return _token_cache[0]


def download_media(media_id: str) -> tuple[bytes, str]:
    """Download a file from WeCom media API. Returns (file_bytes, filename_hint)."""
    token = _get_token()
    url = f"{WECOM_API}/media/get?access_token={token}&media_id={media_id}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=60) as resp:
        content_type = resp.headers.get("Content-Type", "")
        if "application/json" in content_type or "text" in content_type:
            body = resp.read()
            err = json.loads(body)
            raise RuntimeError(f"WeCom media download failed: {err.get('errmsg')}")
        data = resp.read()
        cd = resp.headers.get("Content-Disposition", "")
        filename = media_id
        if cd:
            m_star = re.search(r"filename\*\s*=\s*[^']*''([^;]+)", cd, re.IGNORECASE)
            if m_star:
                filename = unquote(m_star.group(1).strip().strip('"'))
            else:
                m = re.search(r'filename\s*=\s*"?(?P<name>[^";]+)"?', cd, re.IGNORECASE)
                if m:
                    filename = m.group("name").strip()
        return data, filename


def send_text(user_id: str, content: str) -> bool:
    """Send a text message to a WeCom user via the app."""
    if not user_id or not content:
        return False
    try:
        token = _get_token()
        payload = {
            "touser": user_id,
            "msgtype": "text",
            "agentid": AGENT_ID,
            "text": {"content": content[:2048]},
        }
        url = f"{WECOM_API}/message/send?access_token={token}"
        body = json.dumps(payload, ensure_ascii=False).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        if data.get("errcode", 0) != 0:
            logger.warning("WeCom send failed: %s", data.get("errmsg"))
            return False
        logger.info("WeCom message sent to %s (%d chars)", user_id, len(content))
        return True
    except Exception as e:
        logger.error("WeCom send error: %s", e)
        return False


def upload_file(filepath: str) -> str | None:
    """Upload a file to WeCom and return media_id.

    Uses the media/upload API. Supports file type.
    Returns media_id string or None on failure.
    """
    token = _get_token()
    url = f"{WECOM_API}/media/upload?access_token={token}&type=file"
    try:
        import http.client
        # Read file content
        with open(filepath, "rb") as f:
            file_data = f.read()
        filename = os.path.basename(filepath)
        # Build multipart form data manually
        boundary = f"----WebKitFormBoundary{os.urandom(16).hex()}"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="media"; filename="{filename}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode("utf-8")
        body += file_data
        body += f"\r\n--{boundary}--\r\n".encode("utf-8")

        req = urllib.request.Request(url, data=body)
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
        if data.get("errcode", 0) != 0:
            logger.warning("WeCom file upload failed: %s", data.get("errmsg"))
            return None
        media_id = data.get("media_id", "")
        logger.info("WeCom file uploaded: %s -> %s", filename, media_id)
        return media_id
    except Exception as e:
        logger.error("WeCom file upload error: %s", e)
        return None


def send_file(user_id: str, filepath: str) -> bool:
    """Upload a file and send it as a file message to a user."""
    media_id = upload_file(filepath)
    if not media_id:
        return False
    token = _get_token()
    url = f"{WECOM_API}/message/send?access_token={token}"
    body = json.dumps({
        "touser": user_id,
        "msgtype": "file",
        "agentid": AGENT_ID,
        "file": {"media_id": media_id},
        "safe": 0,
        "enable_duplicate_check": 0,
    }).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        if data.get("errcode", 0) != 0:
            logger.warning("WeCom send_file failed: %s", data.get("errmsg"))
            return False
        logger.info("File sent to %s via WeCom", user_id)
        return True
    except Exception as e:
        logger.error("WeCom send_file error: %s", e)
        return False


def send_file_card(user_id: str, filename: str, download_url: str) -> bool:
    """Send a rich textcard with download button — reliably delivers to chat."""
    token = _get_token()
    url = f"{WECOM_API}/message/send?access_token={token}"
    body = json.dumps({
        "touser": user_id,
        "msgtype": "textcard",
        "agentid": AGENT_ID,
        "textcard": {
            "title": filename,
            "description": '<div class=\"normal\">文档已生成，点击下方按钮下载</div>',
            "url": download_url,
            "btntxt": "下载文档",
        },
    }, ensure_ascii=False).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        if data.get("errcode", 0) != 0:
            logger.warning("WeCom send_file_card failed: %s", data.get("errmsg"))
            return False
        logger.info("File card sent to %s via WeCom", user_id)
        return True
    except Exception as e:
        logger.error("WeCom send_file_card error: %s", e)
        return False
