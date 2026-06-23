from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch


class TestScopePromotionTools(unittest.TestCase):
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

    def test_write_scoped_memory_tool(self) -> None:
        from src.tools.memory_scope_tools import write_scoped_memory_tool

        result = write_scoped_memory_tool(
            {"scope_type": "department", "scope_id": "2", "content": "技术部流程更新", "source": "manual"}
        )

        self.assertIn("已写入作用域记忆", result)

    def test_promote_scoped_memory_tool(self) -> None:
        from src.memory.scoped_store import ScopedMemoryStore
        from src.store.database import Database
        from src.tools.memory_scope_tools import promote_scoped_memory_tool

        store = ScopedMemoryStore(Database.get(self.tmp).connect())
        store.retain("可复用经验", scope_type="personal", scope_id="u1", source="chat")

        result = promote_scoped_memory_tool(
            {
                "source_scope_type": "personal",
                "source_scope_id": "u1",
                "target_scope_type": "project",
                "target_scope_id": "proj-1",
                "query": "可复用经验",
            }
        )

        self.assertIn("已升级 1 条记忆", result)

    def test_promote_knowledge_tool(self) -> None:
        from src.knowledge.contracts import KnowledgeEntry, KnowledgeOwnerType
        from src.tools.knowledge_tools import promote_knowledge_tool

        class FakeRepo:
            def get(self, entry_id: str):
                return KnowledgeEntry(
                    id=entry_id,
                    owner_type=KnowledgeOwnerType.PROJECT,
                    owner_id="proj-1",
                    content="项目经验",
                    tags=["summary"],
                )

        with (
            patch("src.knowledge.gbrain_repo.GbrainKnowledgeRepository", return_value=FakeRepo()),
            patch("src.knowledge.service.KnowledgeService") as mock_service_cls,
        ):
            mock_service = mock_service_cls.return_value
            mock_service.promote_entry.return_value = type("Entry", (), {"id": "k1-promoted"})()
            result = promote_knowledge_tool({"entry_id": "k1", "target_scope": "department", "target_id": "2"})

        self.assertIn("已将知识条目 k1 升级为 department/2", result)
