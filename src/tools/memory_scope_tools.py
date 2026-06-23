from __future__ import annotations

from typing import Any

from src.memory.scoped_store import ScopedMemoryStore
from src.store.database import Database


def write_scoped_memory_tool(args: dict[str, Any]) -> str:
    scope_type = str(args.get("scope_type", "personal"))
    scope_id = str(args.get("scope_id", ""))
    content = str(args.get("content", ""))
    source = str(args.get("source", "manual"))
    if not scope_id or not content:
        return "请提供 scope_id 和 content"
    store = ScopedMemoryStore(Database.get().connect())
    memory_id = store.retain(content, scope_type=scope_type, scope_id=scope_id, source=source)
    return f"已写入作用域记忆：{scope_type}/{scope_id} ({memory_id})"


def promote_scoped_memory_tool(args: dict[str, Any]) -> str:
    source_scope_type = str(args.get("source_scope_type", "personal"))
    source_scope_id = str(args.get("source_scope_id", ""))
    target_scope_type = str(args.get("target_scope_type", "project"))
    target_scope_id = str(args.get("target_scope_id", ""))
    query = str(args.get("query", ""))
    if not source_scope_id or not target_scope_id or not query:
        return "请提供 source_scope_id、target_scope_id 和 query"
    store = ScopedMemoryStore(Database.get().connect())
    count = store.promote(
        source_scope_type=source_scope_type,
        source_scope_id=source_scope_id,
        target_scope_type=target_scope_type,
        target_scope_id=target_scope_id,
        query=query,
    )
    return f"已升级 {count} 条记忆到 {target_scope_type}/{target_scope_id}"
