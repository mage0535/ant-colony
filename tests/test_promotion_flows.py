from __future__ import annotations

import os
import tempfile
import unittest


class TestPromotionFlows(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mktemp(suffix=".db")
        os.environ["ANT_COLONY_DB_PATH"] = self.tmp

    def tearDown(self) -> None:
        from src.store.database import Database

        Database.get(self.tmp).close()
        Database._instances.pop(self.tmp, None)  # type: ignore[attr-defined]
        try:
            os.remove(self.tmp)
        except OSError:
            pass
        os.environ.pop("ANT_COLONY_DB_PATH", None)

    def test_knowledge_service_can_promote_project_entry_to_department(self) -> None:
        from src.knowledge.contracts import InMemoryKnowledgeRepository, KnowledgeOwnerType
        from src.knowledge.service import KnowledgeService

        repo = InMemoryKnowledgeRepository()
        service = KnowledgeService(repo)
        entry = service.save_project_entry("proj-1", "k1", "项目结论", tags=["summary"])
        promoted = service.promote_entry(
            entry,
            target_owner_type=KnowledgeOwnerType.DEPARTMENT,
            target_owner_id="2",
            new_entry_id="k2",
            extra_tags=["promoted"],
        )

        self.assertEqual(promoted.owner_type, KnowledgeOwnerType.DEPARTMENT)
        self.assertIn("promoted", promoted.tags)
        self.assertEqual(promoted.metadata["promoted_from"], "k1")

    def test_scoped_memory_can_promote_personal_memory_to_project(self) -> None:
        from src.memory.scoped_store import ScopedMemoryStore
        from src.store.database import Database

        store = ScopedMemoryStore(Database.get(self.tmp).connect())
        store.retain("用户提出一个可复用经验", scope_type="personal", scope_id="u1", source="chat")
        count = store.promote(
            source_scope_type="personal",
            source_scope_id="u1",
            target_scope_type="project",
            target_scope_id="proj-1",
            query="可复用经验",
        )
        promoted = store.recall("可复用经验", scopes=[("project", "proj-1")])

        self.assertEqual(count, 1)
        self.assertEqual(len(promoted), 1)
