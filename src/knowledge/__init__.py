"""Knowledge and memory integration layer."""

from src.knowledge.contracts import InMemoryKnowledgeRepository, KnowledgeEntry, KnowledgeOwnerType, KnowledgeRepository
from src.knowledge.fts_repo import FtsKnowledgeRepository
from src.knowledge.project_summary_service import ProjectSummaryService
from src.knowledge.service import KnowledgeService

__all__ = [
    "InMemoryKnowledgeRepository",
    "FtsKnowledgeRepository",
    "KnowledgeEntry",
    "KnowledgeOwnerType",
    "KnowledgeRepository",
    "ProjectSummaryService",
    "KnowledgeService",
]
