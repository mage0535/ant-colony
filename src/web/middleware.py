from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

# Simple token-based auth: shared secret in Authorization header
# Set ANT_COLONY_AUTH_TOKEN env var, or defaults to no-auth
import os
AUTH_TOKEN = os.environ.get("ANT_COLONY_AUTH_TOKEN", "")


def require_auth(request: Request) -> None:
    if not AUTH_TOKEN:
        return
    auth = request.headers.get("Authorization", "")
    if not auth:
        raise HTTPException(401, detail="Authorization header required")
    if auth == f"Bearer {AUTH_TOKEN}":
        return
    raise HTTPException(403, detail="Invalid token")


# Simple rate limiter: in-memory sliding window per IP
_requests: dict[str, list[float]] = {}
RATE_LIMIT = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "300"))
RATE_WINDOW = 60


def check_rate_limit(request: Request) -> None:
    if RATE_LIMIT <= 0:
        return
    client = request.client.host if request.client else "unknown"
    now = time.time()
    if client not in _requests:
        _requests[client] = []
    window = [t for t in _requests[client] if now - t < RATE_WINDOW]
    if len(window) >= RATE_LIMIT:
        raise HTTPException(429, detail="Rate limit exceeded")
    window.append(now)
    _requests[client] = window
    # Cleanup every 100 requests
    if len(_requests) > 10000:
        for k in list(_requests.keys()):
            _requests[k] = [t for t in _requests[k] if now - t < RATE_WINDOW]
            if not _requests[k]:
                del _requests[k]


# Request ID middleware
import uuid as _uuid

def add_request_id(request: Request) -> str:
    rid = request.headers.get("X-Request-ID", str(_uuid.uuid4())[:8])
    return rid
