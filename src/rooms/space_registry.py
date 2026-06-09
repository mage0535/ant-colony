from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SpaceRecord:
    space_id: str
    name: str
    space_type: str = "project"
    description: str = ""
    members: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class SpaceRegistry:
    """Formal space lifecycle — create, list, track members and stats.

    Spaces are persisted in the tasks.sqlite database as space_meta rows.
    Implicit spaces (auto-created when messages arrive) are detected and
    registered on first access.
    """

    def __init__(self, repo: Any = None) -> None:
        self._repo = repo
        self._cache: dict[str, SpaceRecord] = {}

    def register(self, space_id: str, name: str = "", space_type: str = "project",
                 description: str = "", members: list[str] | None = None) -> SpaceRecord:
        existing = self._cache.get(space_id)
        if existing:
            if name:
                existing.name = name
            if members:
                existing.members = list(dict.fromkeys(existing.members + members))
            self._persist(existing)
            return existing
        record = SpaceRecord(
            space_id=space_id,
            name=name or space_id,
            space_type=space_type,
            description=description,
            members=members or [],
        )
        self._cache[space_id] = record
        self._persist(record)
        logger.info("SpaceRegistry: registered space %s (%s)", space_id, name or space_id)
        return record

    def get(self, space_id: str) -> SpaceRecord | None:
        if space_id not in self._cache and self._repo is not None:
            self._load_from_db(space_id)
        return self._cache.get(space_id)

    def list_all(self) -> list[SpaceRecord]:
        if self._repo is not None:
            self._load_all_from_db()
        return sorted(self._cache.values(), key=lambda r: r.space_id)

    def add_member(self, space_id: str, user_id: str) -> SpaceRecord | None:
        record = self.get(space_id)
        if record is None:
            record = self.register(space_id)
        if user_id not in record.members:
            record.members.append(user_id)
            self._persist(record)
        return record

    def delete(self, space_id: str) -> bool:
        if space_id in self._cache:
            del self._cache[space_id]
        if self._repo is not None:
            self._repo._conn.execute("DELETE FROM space_meta WHERE space_id = ?", (space_id,))
            self._repo._conn.commit()
            return True
        return space_id not in self._cache

    def stats(self) -> dict[str, Any]:
        records = self.list_all()
        return {
            "total_spaces": len(records),
            "spaces": [
                {
                    "space_id": r.space_id,
                    "name": r.name,
                    "type": r.space_type,
                    "members": len(r.members),
                    "description": r.description,
                }
                for r in records
            ],
        }

    def _persist(self, record: SpaceRecord) -> None:
        if self._repo is None:
            return
        self._repo._conn.execute(
            """INSERT OR REPLACE INTO space_meta (space_id, name, space_type, description, members)
               VALUES (?, ?, ?, ?, ?)""",
            (record.space_id, record.name, record.space_type, record.description,
             json.dumps(record.members, ensure_ascii=False)),
        )
        self._repo._conn.commit()

    def _load_from_db(self, space_id: str) -> None:
        if self._repo is None:
            return
        row = self._repo._conn.execute(
            "SELECT * FROM space_meta WHERE space_id = ?", (space_id,)
        ).fetchone()
        if row:
            self._cache[row["space_id"]] = SpaceRecord(
                space_id=row["space_id"],
                name=row["name"],
                space_type=row["space_type"],
                description=row["description"],
                members=json.loads(row["members"]),
            )

    def _load_all_from_db(self) -> None:
        if self._repo is None:
            return
        rows = self._repo._conn.execute("SELECT * FROM space_meta ORDER BY space_id").fetchall()
        for row in rows:
            sid = row["space_id"]
            if sid not in self._cache:
                self._cache[sid] = SpaceRecord(
                    space_id=sid,
                    name=row["name"],
                    space_type=row["space_type"],
                    description=row["description"],
                    members=json.loads(row["members"]),
                )
