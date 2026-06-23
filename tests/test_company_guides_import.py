from __future__ import annotations

import unittest


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


if __name__ == "__main__":
    unittest.main()
