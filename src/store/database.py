from __future__ import annotations

import logging
import os
import sqlite3
import threading

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS task_drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL,
    assignee_user_id TEXT DEFAULT NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    source_message_ids TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL,
    assignee_user_id TEXT DEFAULT NULL,
    collaborator_ids TEXT NOT NULL DEFAULT '[]',
    source_message_ids TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'draft',
    due_at TEXT DEFAULT NULL,
    blocked_reason TEXT DEFAULT NULL,
    blocked_by_task_id TEXT DEFAULT NULL,
    priority TEXT NOT NULL DEFAULT 'medium',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS space_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    space_id TEXT NOT NULL,
    from_user_id TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    processed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    space_id TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL DEFAULT '',
    dismissed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS space_meta (
    space_id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    space_type TEXT NOT NULL DEFAULT 'project',
    description TEXT NOT NULL DEFAULT '',
    members TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class Database:
    _instances: dict[str, Database] = {}
    _lock = threading.Lock()

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    @classmethod
    def get(cls, db_path: str = "") -> Database:
        path = db_path or os.environ.get("ANT_COLONY_DB_PATH", "./data/ant-colony.db")
        with cls._lock:
            if path not in cls._instances:
                cls._instances[path] = Database(path)
            return cls._instances[path]

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.row_factory = sqlite3.Row
            self._init_schema()
            logger.info("Database opened: %s", self.db_path)
        return self._conn

    def _init_schema(self) -> None:
        if self._conn is None:
            return
        for statement in _SCHEMA.strip().split(";"):
            s = statement.strip()
            if s:
                self._conn.execute(s)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        if self._conn is None:
            return
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(tasks)").fetchall()}
        if "blocked_by_task_id" not in cols:
            self._conn.execute("ALTER TABLE tasks ADD COLUMN blocked_by_task_id TEXT DEFAULT NULL")
            logger.info("Migration: added blocked_by_task_id to tasks")
        if "priority" not in cols:
            self._conn.execute("ALTER TABLE tasks ADD COLUMN priority TEXT NOT NULL DEFAULT 'medium'")
            logger.info("Migration: added priority to tasks")
        tables = {r[0] for r in self._conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "space_meta" not in tables:
            self._conn.execute(
                """CREATE TABLE space_meta (
                    space_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL DEFAULT '',
                    space_type TEXT NOT NULL DEFAULT 'project',
                    description TEXT NOT NULL DEFAULT '',
                    members TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )"""
            )
            logger.info("Migration: created space_meta table")
        if "knowledge_items" not in tables:
            self._conn.execute(
                """CREATE TABLE knowledge_items (
                    id TEXT PRIMARY KEY,
                    owner_type TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tags TEXT NOT NULL DEFAULT '[]',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    read_roles TEXT NOT NULL DEFAULT '["self"]',
                    write_roles TEXT NOT NULL DEFAULT '["admin","self"]',
                    created_at REAL NOT NULL DEFAULT (cast(strftime('%s','now') as real))
                )"""
            )
            self._conn.execute(
                """CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts
                   USING fts5(id, owner_type, owner_id, content, tags, tokenize='unicode61')"""
            )
            logger.info("Migration: created knowledge_items and knowledge_fts")
        # ACL column migration for existing knowledge_items tables
        else:
            knowledge_cols = {r[1] for r in self._conn.execute("PRAGMA table_info(knowledge_items)").fetchall()}
            for col, default_val in [("read_roles", '["self"]'), ("write_roles", '["admin","self"]')]:
                if col not in knowledge_cols:
                    try:
                        self._conn.execute(
                            f"ALTER TABLE knowledge_items ADD COLUMN {col} TEXT NOT NULL DEFAULT '{default_val}'"
                        )
                        logger.info("Migration: added %s to knowledge_items", col)
                    except Exception:
                        pass

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
