from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch


class TestFtsFallback(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mktemp(suffix=".db")
        os.environ["ANT_COLONY_DB_PATH"] = self.tmp

    def tearDown(self) -> None:
        from src.store.database import Database

        Database.get(self.tmp).close()
        Database._instances.pop(self.tmp, None)  # type: ignore[attr-defined]
        os.environ.pop("ANT_COLONY_DB_PATH", None)
        try:
            os.remove(self.tmp)
        except OSError:
            pass

    def test_search_accessible_falls_back_to_like_when_fts_raises(self) -> None:
        from src.knowledge.contracts import KnowledgeEntry, KnowledgeOwnerType
        from src.knowledge.fts_repo import FtsKnowledgeRepository
        from src.store.database import Database

        repo = FtsKnowledgeRepository(Database.get(self.tmp).connect())
        repo.save(
            KnowledgeEntry(
                id="k1",
                owner_type=KnowledgeOwnerType.ORGANIZATION,
                owner_id="*",
                content="企业微信 AI 助手激活说明书\n\n第一步 打开企业微信",
                tags=["激活", "说明书"],
                metadata={"title": "企业微信 AI 助手激活说明书"},
                read_roles=["*"],
                write_roles=["admin", "leader"],
            )
        )

        original_conn = repo._conn

        class FlakyConnection:
            def execute(self, sql, params=()):
                if "knowledge_fts MATCH" in sql:
                    raise __import__("sqlite3").OperationalError("fts5 syntax error")
                return original_conn.execute(sql, params)

        repo._conn = FlakyConnection()  # type: ignore[assignment]

        with patch("src.knowledge.acl.resolve_role") as mock_role, \
             patch("src.knowledge.acl.may_read", return_value=True):
            mock_role.return_value = type("RoleValue", (), {"value": 3})()
            results = repo.search_accessible("企业微信 激活 机器人 说明书", user_id="u1", limit=5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].metadata["title"], "企业微信 AI 助手激活说明书")

    def test_search_skips_invalid_historical_owner_type_rows(self) -> None:
        from src.knowledge.contracts import KnowledgeEntry, KnowledgeOwnerType
        from src.knowledge.fts_repo import FtsKnowledgeRepository
        from src.store.database import Database

        repo = FtsKnowledgeRepository(Database.get(self.tmp).connect())
        repo.save(
            KnowledgeEntry(
                id="valid",
                owner_type=KnowledgeOwnerType.ORGANIZATION,
                owner_id="*",
                content="企业 AI 助手公共数据源说明",
                tags=["公共数据"],
                metadata={"title": "公共数据源说明"},
                read_roles=["*"],
                write_roles=["admin"],
            )
        )
        conn = repo._conn
        conn.execute(
            """
            INSERT INTO knowledge_items
                (id, owner_type, owner_id, content, tags, metadata_json, read_roles, write_roles)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("bad-owner", "", "*", "企业 AI 助手公共数据源坏数据", '["公共数据"]', '{"title":"坏数据"}', '["*"]', '["admin"]'),
        )
        conn.execute(
            "INSERT INTO knowledge_fts (id, owner_type, owner_id, content, tags) VALUES (?, ?, ?, ?, ?)",
            ("bad-owner", "", "*", "企业 AI 助手公共数据源坏数据", '["公共数据"]'),
        )
        conn.commit()

        results = repo.search("AI", limit=10)

        self.assertEqual([item.id for item in results], ["valid"])


if __name__ == "__main__":
    unittest.main()
