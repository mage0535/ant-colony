from __future__ import annotations

import unittest
from unittest.mock import patch


class TestKnowledgeManagementApi(unittest.TestCase):
    def test_search_knowledge_route_prefers_accessible_search_when_user_present(self) -> None:
        from src.web.dashboard import search_knowledge
        from src.knowledge.contracts import KnowledgeEntry, KnowledgeOwnerType

        entry = KnowledgeEntry(
            id="k1",
            owner_type=KnowledgeOwnerType.ORGANIZATION,
            owner_id="*",
            content="企业微信 AI 助手激活说明书\n\n正文",
            tags=["guide"],
            metadata={"title": "企业微信 AI 助手激活说明书"},
        )
        fake_repo = type("Repo", (), {"search_accessible": lambda self, query, user_id="", space_id="", limit=20: [entry]})()

        with patch("src.web.dashboard.get_knowledge_repo", return_value=fake_repo):
            result = search_knowledge("激活", user_id="u1", space_id="", limit=10)

        self.assertEqual(result["results"][0]["title"], "企业微信 AI 助手激活说明书")

    def test_import_company_guides_api_returns_imported_entries(self) -> None:
        from src.web.dashboard import import_company_guides_api
        from src.knowledge.contracts import KnowledgeEntry, KnowledgeOwnerType

        entries = [
            KnowledgeEntry(
                id="company-guide-wecom-activation",
                owner_type=KnowledgeOwnerType.ORGANIZATION,
                owner_id="*",
                content="content",
                tags=["guide"],
                metadata={"title": "企业微信 AI 助手激活说明书"},
            )
        ]

        with patch("src.web.dashboard.get_knowledge_repo", return_value=object()), \
             patch("src.knowledge.company_guides.import_company_guides", return_value=entries):
            result = import_company_guides_api()

        self.assertEqual(result["imported"], 1)
        self.assertEqual(result["entries"][0]["title"], "企业微信 AI 助手激活说明书")


if __name__ == "__main__":
    unittest.main()
