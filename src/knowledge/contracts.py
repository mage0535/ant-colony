from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class KnowledgeOwnerType(str, Enum):
    PERSONAL = "personal"
    PROJECT = "project"
    DEPARTMENT = "department"
    ORGANIZATION = "organization"


class PermissionLevel(str, Enum):
    READ = "read"
    WRITE = "write"


@dataclass(slots=True)
class KnowledgeEntry:
    id: str
    owner_type: KnowledgeOwnerType
    owner_id: str
    content: str
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    # Security: who can read / who can write
    #   read_roles: list of role names e.g. ["admin","leader","member","self"]
    #   write_roles: same format
    #   Default read: everyone for org/dep/project, self+admin for personal
    #   Default write: admin+leader for org/dep, admin+member for project, admin+self for personal
    read_roles: list[str] = field(default_factory=list)
    write_roles: list[str] = field(default_factory=list)


class KnowledgeRepository(Protocol):
    def save(self, entry: KnowledgeEntry) -> KnowledgeEntry:
        ...

    def list_for_owner(self, owner_type: KnowledgeOwnerType, owner_id: str) -> list[KnowledgeEntry]:
        ...


class InMemoryKnowledgeRepository:
    def __init__(self) -> None:
        self._entries: dict[str, KnowledgeEntry] = {}

    def save(self, entry: KnowledgeEntry) -> KnowledgeEntry:
        self._entries[entry.id] = entry
        return entry

    def list_for_owner(self, owner_type: KnowledgeOwnerType, owner_id: str) -> list[KnowledgeEntry]:
        return [
            entry
            for entry in self._entries.values()
            if entry.owner_type == owner_type and entry.owner_id == owner_id
        ]
