from __future__ import annotations

from src.knowledge.contracts import KnowledgeEntry, KnowledgeOwnerType, KnowledgeRepository


class KnowledgeService:
    """Minimal knowledge-domain service for M1.

    M1 only needs enough structure to distinguish personal and project
    knowledge. Real Sidecar / RAG integration can replace the repository
    implementation later without changing this service contract.
    """

    def __init__(self, repository: KnowledgeRepository) -> None:
        self.repository = repository

    def save_personal_entry(self, user_id: str, entry_id: str, content: str, tags: list[str] | None = None) -> KnowledgeEntry:
        entry = KnowledgeEntry(
            id=entry_id,
            owner_type=KnowledgeOwnerType.PERSONAL,
            owner_id=user_id,
            content=content,
            tags=tags or [],
        )
        return self.repository.save(entry)

    def save_project_entry(
        self, project_id: str, entry_id: str, content: str, tags: list[str] | None = None
    ) -> KnowledgeEntry:
        entry = KnowledgeEntry(
            id=entry_id,
            owner_type=KnowledgeOwnerType.PROJECT,
            owner_id=project_id,
            content=content,
            tags=tags or [],
        )
        return self.repository.save(entry)

    def save_department_entry(
        self, dept_id: str, entry_id: str, content: str, tags: list[str] | None = None
    ) -> KnowledgeEntry:
        entry = KnowledgeEntry(
            id=entry_id,
            owner_type=KnowledgeOwnerType.DEPARTMENT,
            owner_id=dept_id,
            content=content,
            tags=tags or [],
        )
        return self.repository.save(entry)

    def save_organization_entry(
        self, entry_id: str, content: str, tags: list[str] | None = None
    ) -> KnowledgeEntry:
        entry = KnowledgeEntry(
            id=entry_id,
            owner_type=KnowledgeOwnerType.ORGANIZATION,
            owner_id="*",
            content=content,
            tags=tags or [],
        )
        return self.repository.save(entry)

    def list_personal_entries(self, user_id: str) -> list[KnowledgeEntry]:
        return self.repository.list_for_owner(KnowledgeOwnerType.PERSONAL, user_id)

    def list_project_entries(self, project_id: str) -> list[KnowledgeEntry]:
        return self.repository.list_for_owner(KnowledgeOwnerType.PROJECT, project_id)

    def list_department_entries(self, dept_id: str) -> list[KnowledgeEntry]:
        return self.repository.list_for_owner(KnowledgeOwnerType.DEPARTMENT, dept_id)

    def list_organization_entries(self) -> list[KnowledgeEntry]:
        return self.repository.list_for_owner(KnowledgeOwnerType.ORGANIZATION, "*")

    def promote_entry(
        self,
        entry: KnowledgeEntry,
        *,
        target_owner_type: KnowledgeOwnerType,
        target_owner_id: str,
        new_entry_id: str,
        extra_tags: list[str] | None = None,
    ) -> KnowledgeEntry:
        promoted = KnowledgeEntry(
            id=new_entry_id,
            owner_type=target_owner_type,
            owner_id=target_owner_id,
            content=entry.content,
            tags=list(dict.fromkeys(entry.tags + (extra_tags or []))),
            metadata={**entry.metadata, "promoted_from": entry.id},
            read_roles=list(entry.read_roles),
            write_roles=list(entry.write_roles),
        )
        return self.repository.save(promoted)
