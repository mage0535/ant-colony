from __future__ import annotations

from pathlib import Path

from src.knowledge.contracts import KnowledgeEntry, KnowledgeOwnerType

_GUIDE_FILES = [
    (
        "company-guide-wecom-activation",
        "企业微信 AI 助手激活说明书",
        "docs/wecom-ai-assistant-activation-guide.md",
        ["guide", "manual", "wecom", "activation", "ai助手", "企业微信", "机器人", "激活"],
    ),
    (
        "company-guide-wecom-features",
        "企业微信 AI 助手功能与操作说明书",
        "docs/wecom-ai-assistant-feature-guide.md",
        ["guide", "manual", "wecom", "feature", "usage", "ai助手", "企业微信", "功能", "操作", "说明书"],
    ),
    (
        "company-guide-knowledge-base",
        "企业知识库分级建设与管理说明书",
        "docs/knowledge-base-operations-guide.md",
        ["guide", "manual", "knowledge", "knowledge-base", "管理", "知识库", "说明书", "company", "organization"],
    ),
]


def build_company_guide_entries() -> list[KnowledgeEntry]:
    project_root = Path(__file__).resolve().parents[2]
    entries: list[KnowledgeEntry] = []
    for entry_id, title, relative_path, tags in _GUIDE_FILES:
        path = project_root / relative_path
        content = path.read_text(encoding="utf-8")
        normalized_content = f"{title}\n\n{content}"
        entries.append(
            KnowledgeEntry(
                id=entry_id,
                owner_type=KnowledgeOwnerType.ORGANIZATION,
                owner_id="*",
                content=normalized_content,
                tags=tags,
                metadata={
                    "title": title,
                    "source_type": "builtin_company_guide",
                    "source_path": relative_path,
                    "stable": True,
                },
                read_roles=["*"],
                write_roles=["admin"],
            )
        )
    return entries


def import_company_guides(repo) -> list[KnowledgeEntry]:
    entries = build_company_guide_entries()
    saved: list[KnowledgeEntry] = []
    for entry in entries:
        saved.append(repo.save(entry))
    return saved
