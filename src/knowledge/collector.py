from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlparse

from src.knowledge.contracts import KnowledgeEntry, KnowledgeOwnerType
from src.knowledge.fts_repo import FtsKnowledgeRepository
from src.knowledge.document_converter import convert_document, guess_type

logger = logging.getLogger(__name__)


def _acl_for_owner_type(owner_type: str) -> tuple[list[str], list[str]]:
    """Return default (read_roles, write_roles) for a given owner_type."""
    defaults = {
        "personal":     (["self"],         ["admin", "self"]),
        "project":      (["*"],            ["admin", "member"]),
        "department":   (["*"],            ["admin", "leader"]),
        "organization": (["*"],            ["admin", "leader"]),
    }
    return defaults.get(owner_type, (["*"], ["admin"]))


class KnowledgeCollector:
    """Ingestion pipeline: scrape URLs, parse text files, auto-index into FTS5.

    Accepts a FtsKnowledgeRepository and provides batch collection methods
    for URLs, plain text, and local files.

    Each collected entry automatically gets ACL roles based on its owner_type.
    """

    def __init__(self, repo: FtsKnowledgeRepository) -> None:
        self.repo = repo

    def _make_entry(self, entry_id: str, owner_type: str, owner_id: str, content: str,
                    tags: list[str] | None = None) -> KnowledgeEntry:
        read_roles, write_roles = _acl_for_owner_type(owner_type)
        return KnowledgeEntry(
            id=entry_id,
            owner_type=KnowledgeOwnerType(owner_type),
            owner_id=owner_id,
            content=content,
            tags=tags or [],
            read_roles=read_roles,
            write_roles=write_roles,
        )

    def collect_url(self, url: str, owner_type: str = "project", owner_id: str = "*",
                    tags: list[str] | None = None) -> KnowledgeEntry | None:
        try:
            import urllib.request
            req = urllib.request.Request(url, headers={"User-Agent": "AntColony/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                content = resp.read().decode("utf-8", errors="replace")[:50000]
        except Exception as e:
            logger.warning("Failed to fetch %s: %s", url, e)
            return None

        parsed = urlparse(url)
        domain_tag = parsed.netloc.split(".")[-2] if "." in parsed.netloc else parsed.netloc
        entry = self._make_entry(
            entry_id=_url_to_id(url),
            owner_type=owner_type, owner_id=owner_id,
            content=f"URL: {url}\nSource: {parsed.netloc}\n\n{_strip_html(content)}",
            tags=(tags or []) + ["url", domain_tag],
        )
        self.repo.save(entry)
        logger.info("Collected URL %s as %s (%d chars)", url, entry.id, len(entry.content))
        return entry

    def collect_text(self, text: str, title: str, owner_type: str = "project",
                     owner_id: str = "*", tags: list[str] | None = None) -> KnowledgeEntry:
        import uuid
        entry = self._make_entry(
            entry_id=f"txt-{uuid.uuid4().hex[:12]}",
            owner_type=owner_type, owner_id=owner_id,
            content=f"{title}\n\n{text}",
            tags=tags or [],
        )
        self.repo.save(entry)
        logger.info("Collected text %s as %s", title, entry.id)
        return entry

    def collect_file(self, filepath: str, owner_type: str = "project",
                     owner_id: str = "*", tags: list[str] | None = None) -> KnowledgeEntry | None:
        if not os.path.isfile(filepath):
            logger.warning("File not found: %s", filepath)
            return None
        title = os.path.basename(filepath)
        ext = os.path.splitext(title)[1].lstrip(".")
        ftype = guess_type(filepath)
        if ftype != "text":
            content = convert_document(filepath)
            if content is None:
                logger.warning("Falling back to raw text for %s", filepath)
                content = _read_raw(filepath)
            tags_extra = ["document", ext, ftype]
        else:
            content = _read_raw(filepath)
            tags_extra = ["file", ext] if ext else ["file"]
        if not content:
            return None
        entry = self._make_entry(
            entry_id=f"file-{_hash_url(filepath)[:12]}",
            owner_type=owner_type, owner_id=owner_id,
            content=content[:100000],
            tags=(tags or []) + tags_extra,
        )
        self.repo.save(entry)
        logger.info("Collected file %s as %s (%d chars, type=%s)", filepath, entry.id, len(entry.content), ftype)
        return entry

    def stats(self) -> dict[str, Any]:
        return {"repo": self.repo.stats()}


def _url_to_id(url: str) -> str:
    import hashlib
    return f"url-{hashlib.sha256(url.encode()).hexdigest()[:16]}"


def _hash_url(url: str) -> str:
    import hashlib
    return hashlib.sha256(url.encode()).hexdigest()


def _read_raw(filepath: str) -> str | None:
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            return f.read()[:100000]
    except Exception as e:
        logger.warning("Failed to read %s: %s", filepath, e)
        return None


def _strip_html(html: str) -> str:
    import re
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
