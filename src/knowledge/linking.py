from __future__ import annotations

import os
from pathlib import Path


def knowledge_base_url() -> str:
    return (os.environ.get("ANT_COLONY_DOCUMENT_BASE_URL") or "http://127.0.0.1:18092").rstrip("/")


def build_knowledge_open_url(entry_id: str) -> str:
    return f"{knowledge_base_url()}/api/v1/knowledge/{entry_id}/open"
