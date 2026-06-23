from __future__ import annotations

import unittest
from unittest.mock import patch


class TestCompanyGuidesImport(unittest.TestCase):
    def test_build_company_guide_entries_uses_stable_titles_and_company_scope(self) -> None:
        from src.knowledge.company_guides import build_company_guide_entries

        entries = build_company_guide_entries()

        self.assertEqual(len(entries), 3)
        self.assertEqual({entry.owner_type.value for entry in entries}, {"organization"})
        self.assertEqual({entry.owner_id for entry in entries}, {"*"})
        self.assertTrue(any("激活说明书" in entry.metadata.get("title", "") for entry in entries))
        self.assertTrue(any("知识库分级建设与管理说明书" in entry.metadata.get("title", "") for entry in entries))

    def test_import_company_guides_saves_all_entries(self) -> None:
        from src.knowledge.company_guides import import_company_guides

        class FakeRepo:
            def __init__(self) -> None:
                self.saved = []

            def save(self, entry):
                self.saved.append(entry)
                return entry

        repo = FakeRepo()
        entries = import_company_guides(repo)

        self.assertEqual(len(entries), 3)
        self.assertEqual(len(repo.saved), 3)

    def test_search_knowledge_entries_can_match_long_natural_language_query(self) -> None:
        from src.knowledge.contracts import KnowledgeEntry, KnowledgeOwnerType
        from src.tools.knowledge_tools import search_knowledge_entries

        entry = KnowledgeEntry(
            id="company-guide-wecom-activation",
            owner_type=KnowledgeOwnerType.ORGANIZATION,
            owner_id="*",
            content="企业微信 AI 助手激活说明书\n\n第一步 打开企业微信，第二步 找到机器人。",
            tags=["guide", "wecom", "activation", "机器人", "激活"],
            metadata={"title": "企业微信 AI 助手激活说明书"},
            read_roles=["*"],
            write_roles=["admin", "leader"],
        )

        fake_repo = type(
            "Repo",
            (),
            {
                "search_accessible": lambda self, query, user_id="", space_id="", limit=5: [],
                "list_accessible": lambda self, user_id="", limit=200: [entry],
            },
        )()

        with patch("src.knowledge.repository_factory.build_knowledge_repository", return_value=fake_repo):
            results = search_knowledge_entries("我想让其他同事也激活类似你的员工企微机器人，应该怎么操作", user_id="u1", limit=5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].metadata["title"], "企业微信 AI 助手激活说明书")


if __name__ == "__main__":
    unittest.main()
