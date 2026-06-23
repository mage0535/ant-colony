from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config.file_permissions import restrict_to_owner

logger = logging.getLogger(__name__)

_AUDIT_DIR = Path("data") / "audit"
_AUDIT_DB_FILE = _AUDIT_DIR / "capability_audit.sqlite3"
_LEGACY_AUDIT_FILE = _AUDIT_DIR / "capability_invocations.jsonl"
_AUDIT_FILE = _LEGACY_AUDIT_FILE
_MAX_AUDIT_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CapabilityInvocationContext:
    user_id: str = ""
    platform: str = ""
    transport: str = ""
    scope: str = ""
    scope_id: str = ""
    source_chat_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def coerce_capability_context(context: CapabilityInvocationContext | dict[str, Any] | None) -> CapabilityInvocationContext:
    if context is None:
        return CapabilityInvocationContext()
    if isinstance(context, CapabilityInvocationContext):
        return context
    return CapabilityInvocationContext(
        user_id=str(context.get("user_id", "")),
        platform=str(context.get("platform", "")),
        transport=str(context.get("transport", "")),
        scope=str(context.get("scope", "")),
        scope_id=str(context.get("scope_id", "")),
        source_chat_id=str(context.get("source_chat_id", "")),
        metadata=dict(context.get("metadata", {})) if isinstance(context.get("metadata", {}), dict) else {},
    )


def record_capability_audit(
    capability_id: str,
    provider_id: str,
    provider_label: str,
    success: bool,
    context: CapabilityInvocationContext,
    details: dict[str, Any] | None = None,
) -> None:
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "capability_id": capability_id,
        "provider_id": provider_id,
        "provider_label": provider_label,
        "success": success,
        "context": asdict(context),
        "details": details or {},
    }
    try:
        _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        _migrate_legacy_jsonl_if_present()
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT INTO capability_audit (
                    timestamp,
                    capability_id,
                    provider_id,
                    provider_label,
                    success,
                    user_id,
                    platform,
                    transport,
                    scope,
                    scope_id,
                    source_chat_id,
                    metadata_json,
                    details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["timestamp"],
                    capability_id,
                    provider_id,
                    provider_label,
                    1 if success else 0,
                    context.user_id,
                    context.platform,
                    context.transport,
                    context.scope,
                    context.scope_id,
                    context.source_chat_id,
                    json.dumps(context.metadata, ensure_ascii=False),
                    json.dumps(details or {}, ensure_ascii=False),
                ),
            )
            conn.commit()
        finally:
            conn.close()
        restrict_to_owner(_AUDIT_DB_FILE)
    except OSError as exc:
        logger.warning("Capability audit write failed: %s", exc)


def iter_capability_audit_records(
    *,
    capability_id: str = "",
    provider_id: str = "",
    success: bool | None = None,
) -> list[dict[str, Any]]:
    if not _AUDIT_DB_FILE.exists():
        return []
    query = (
        "SELECT timestamp, capability_id, provider_id, provider_label, success, "
        "user_id, platform, transport, scope, scope_id, source_chat_id, metadata_json, details_json "
        "FROM capability_audit WHERE 1=1"
    )
    params: list[Any] = []
    if capability_id:
        query += " AND capability_id = ?"
        params.append(capability_id)
    if provider_id:
        query += " AND provider_id = ?"
        params.append(provider_id)
    if success is not None:
        query += " AND success = ?"
        params.append(1 if success else 0)
    query += " ORDER BY id DESC"
    conn = _connect()
    try:
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()
    return [
        {
            "timestamp": row[0],
            "capability_id": row[1],
            "provider_id": row[2],
            "provider_label": row[3],
            "success": bool(row[4]),
            "context": {
                "user_id": row[5],
                "platform": row[6],
                "transport": row[7],
                "scope": row[8],
                "scope_id": row[9],
                "source_chat_id": row[10],
                "metadata": json.loads(row[11] or "{}"),
            },
            "details": json.loads(row[12] or "{}"),
        }
        for row in rows
    ]


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_AUDIT_DB_FILE)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS capability_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            capability_id TEXT NOT NULL,
            provider_id TEXT NOT NULL,
            provider_label TEXT NOT NULL,
            success INTEGER NOT NULL,
            user_id TEXT NOT NULL,
            platform TEXT NOT NULL,
            transport TEXT NOT NULL,
            scope TEXT NOT NULL,
            scope_id TEXT NOT NULL,
            source_chat_id TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            details_json TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_capability_audit_capability ON capability_audit(capability_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_capability_audit_provider ON capability_audit(provider_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_capability_audit_success ON capability_audit(success)")
    return conn


def _migrate_legacy_jsonl_if_present() -> None:
    if not _LEGACY_AUDIT_FILE.exists():
        return
    if _LEGACY_AUDIT_FILE.stat().st_size > _MAX_AUDIT_BYTES:
        rotated = _LEGACY_AUDIT_FILE.with_suffix(_LEGACY_AUDIT_FILE.suffix + ".1")
        if rotated.exists():
            rotated.unlink()
        _LEGACY_AUDIT_FILE.replace(rotated)
        restrict_to_owner(rotated)
        return
    try:
        rows = []
        for raw_line in _LEGACY_AUDIT_FILE.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        if not rows:
            _LEGACY_AUDIT_FILE.unlink(missing_ok=True)
            return
        conn = _connect()
        try:
            for payload in rows:
                context = payload.get("context", {}) if isinstance(payload.get("context"), dict) else {}
                conn.execute(
                    """
                    INSERT INTO capability_audit (
                        timestamp, capability_id, provider_id, provider_label, success,
                        user_id, platform, transport, scope, scope_id, source_chat_id,
                        metadata_json, details_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        payload.get("timestamp", ""),
                        payload.get("capability_id", ""),
                        payload.get("provider_id", ""),
                        payload.get("provider_label", ""),
                        1 if payload.get("success") else 0,
                        context.get("user_id", ""),
                        context.get("platform", ""),
                        context.get("transport", ""),
                        context.get("scope", ""),
                        context.get("scope_id", ""),
                        context.get("source_chat_id", ""),
                        json.dumps(context.get("metadata", {}), ensure_ascii=False),
                        json.dumps(payload.get("details", {}), ensure_ascii=False),
                    ),
                )
            conn.commit()
        finally:
            conn.close()
        _LEGACY_AUDIT_FILE.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Capability audit migration failed: %s", exc)
