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

    def list_personal_entries(self, user_id: str) -> list[KnowledgeEntry]:
        return self.repository.list_for_owner(KnowledgeOwnerType.PERSONAL, user_id)

    def list_project_entries(self, project_id: str) -> list[KnowledgeEntry]:
        return self.repository.list_for_owner(KnowledgeOwnerType.PROJECT, project_id)
