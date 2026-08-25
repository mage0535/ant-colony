from __future__ import annotations

import sqlite3

from src.memory.maintenance import MemoryMaintenanceCycle


class _LockedRepo:
    def list_messages(self, *, space_id: str = "", limit: int = 50):
        raise sqlite3.OperationalError("database is locked")


class _RepoWithMessage:
    def list_messages(self, *, space_id: str = "", limit: int = 50):
        return [{"content": "这是一条足够长的测试消息，用来触发归档。"}]

    def mark_messages_processed(self, space_id: str) -> None:
        raise sqlite3.OperationalError("database is locked")


class _WarmStore:
    def retain(self, *args, **kwargs):
        return "fact-1"


class _ColdStore:
    def extract_and_ingest(self, *args, **kwargs):
        return 0


def test_memory_maintenance_skips_when_database_busy_on_list() -> None:
    cycle = MemoryMaintenanceCycle(_LockedRepo(), _WarmStore(), _ColdStore())

    result = cycle.archive_session("space-1")

    assert result["skipped"] == "database_busy"
    assert result["messages_archived"] == 0


def test_memory_maintenance_skips_when_database_busy_on_archive() -> None:
    cycle = MemoryMaintenanceCycle(_RepoWithMessage(), _WarmStore(), _ColdStore())

    result = cycle.archive_session("space-1")

    assert result["skipped"] == "database_busy"
    assert result["facts_retained"] == 1
