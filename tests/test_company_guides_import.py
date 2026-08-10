from __future__ import annotations

import unittest
from unittest.mock import patch


class TestCompanyGuidesImport(unittest.TestCase):
    def test_build_company_guide_entries_uses_stable_titles_and_company_scope(self) -> None:
        from src.knowledge.company_guides import build_company_guide_entries

        entries = build_company_guide_entries()

        self.assertEqual(len(entries), 5)
        self.assertEqual({entry.owner_type.value for entry in entries}, {"organization"})
        self.assertEqual({entry.owner_id for entry in entries}, {"*"})
        self.assertTrue(any(entry.id == "company-guide-role-operation-leave-approval" for entry in entries))
        self.assertTrue(any("审批假期" in entry.metadata.get("title", "") for entry in entries))
        self.assertTrue(any("使用总入口" in entry.metadata.get("title", "") for entry in entries))
        self.assertTrue(any("激活说明书" in entry.metadata.get("title", "") for entry in entries))
        self.assertTrue(any("知识库分级建设与管理说明书" in entry.metadata.get("title", "") for entry in entries))

    def test_leave_approval_role_guide_contains_dynamic_leave_notice_chapters(self) -> None:
        from src.knowledge.company_guides import build_company_guide_entries

        entries = build_company_guide_entries()
        guide = next(entry for entry in entries if entry.id == "company-guide-role-operation-leave-approval")

        self.assertIn("请假前动态个人余额提醒", guide.content)
        self.assertIn("企微请假静态说明", guide.content)
        self.assertIn("员工在 AI 助手里说“我要请假”", guide.content)
        self.assertIn("本文只保留一个文件", guide.content)

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

        self.assertEqual(len(entries), 5)
        self.assertEqual(len(repo.saved), 5)

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

    def test_search_knowledge_entries_falls_back_to_user_manual_for_operation_help_queries(self) -> None:
        from src.knowledge.contracts import KnowledgeEntry, KnowledgeOwnerType
        from src.tools.knowledge_tools import search_knowledge_entries

        manual = KnowledgeEntry(
            id="company-guide-user-manual",
            owner_type=KnowledgeOwnerType.ORGANIZATION,
            owner_id="*",
            content="企业 AI 助手使用说明书\n\n上传文件前先发文件，再发要求。",
            tags=["guide", "manual", "上传文件", "使用说明"],
            metadata={"title": "企业 AI 助手使用说明书"},
            read_roles=["*"],
            write_roles=["admin"],
        )

        class FakeRepo:
            def search_accessible(self, query: str, user_id: str = "", space_id: str = "", limit: int = 5):
                if query == "企业 AI 助手使用总入口":
                    return [manual]
                return []

            def list_accessible(self, user_id: str = "", limit: int = 200):
                return []

        with patch("src.knowledge.repository_factory.build_knowledge_repository", return_value=FakeRepo()):
            results = search_knowledge_entries("我不会上传文件，告诉我具体操作步骤", user_id="u1", limit=5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].metadata["title"], "企业 AI 助手使用说明书")

    def test_search_knowledge_entries_filters_transient_enterprise_query_artifacts(self) -> None:
        from src.knowledge.contracts import KnowledgeEntry, KnowledgeOwnerType
        from src.tools.knowledge_tools import search_knowledge_entries

        class FakeRepo:
            def search_accessible(self, query: str, user_id: str = "", space_id: str = "", limit: int = 5):
                return [
                    KnowledgeEntry(
                        id="txt-old-1",
                        owner_type=KnowledgeOwnerType.PERSONAL,
                        owner_id="u1",
                        content="企业应用查询结果\n\n三号会议室：今天 09:30-10:30",
                        tags=["workflow", "enterprise_app_query"],
                        metadata={"title": "企业应用查询结果", "source_type": "text"},
                    ),
                    KnowledgeEntry(
                        id="guide-1",
                        owner_type=KnowledgeOwnerType.ORGANIZATION,
                        owner_id="*",
                        content="企业 AI 助手使用总入口\n\n互联网检索说明",
                        tags=["guide"],
                        metadata={"title": "企业 AI 助手使用总入口"},
                    ),
                ]

        with patch("src.knowledge.repository_factory.build_knowledge_repository", return_value=FakeRepo()):
            results = search_knowledge_entries("企业应用查询结果", user_id="u1", limit=5)

        self.assertEqual([item.id for item in results], ["guide-1"])


if __name__ == "__main__":
    unittest.main()
