from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.request

logger = logging.getLogger(__name__)

WECOM_API = "https://qyapi.weixin.qq.com/cgi-bin"
CORP_ID = os.environ.get("WECOM_CORP_ID", "")
AGENT_ID = int(os.environ.get("WECOM_AGENT_ID", "1000006"))
APP_SECRET = os.environ.get("WECOM_SECRET", "")

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
        if "filename=" in cd:
            m = re.search(r'filename["\']?\s*:\s*["\']?(.+?)["\']?$', cd, re.IGNORECASE)
            if m:
                filename = m.group(1).strip()
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
