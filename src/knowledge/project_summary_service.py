from __future__ import annotations

from src.knowledge.contracts import KnowledgeOwnerType, KnowledgeRepository


class ProjectSummaryService:
    """Minimal project summary builder for M1.

    This is intentionally heuristic and non-LLM for now. It gives the project
    knowledge layer an output shape that later can be upgraded to richer model-
    generated summaries without changing upstream callers.
    """

    def __init__(self, repository: KnowledgeRepository) -> None:
        self.repository = repository

    def build_summary(self, project_id: str) -> str:
        entries = self.repository.list_for_owner(KnowledgeOwnerType.PROJECT, project_id)
        if not entries:
            return "当前项目知识域中暂无可用于总结的项目条目。"

        lines = [f"- {entry.content}" for entry in entries[:5]]
        return "项目阶段摘要：\n" + "\n".join(lines)
