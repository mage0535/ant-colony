from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch


class TestScopedMemoryStore(unittest.TestCase):
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

    def test_retain_and_recall_by_scope(self) -> None:
        from src.memory.scoped_store import ScopedMemoryStore
        from src.store.database import Database

        store = ScopedMemoryStore(Database.get(self.tmp).connect())
        store.retain("dept policy updated", scope_type="department", scope_id="2", source="sync")
        store.retain("project alpha deadline", scope_type="project", scope_id="proj-1", source="chat")

        dept = store.recall("policy", scopes=[("department", "2")])
        proj = store.recall("deadline", scopes=[("project", "proj-1")])

        self.assertEqual(len(dept), 1)
        self.assertEqual(dept[0]["scope_type"], "department")
        self.assertEqual(len(proj), 1)
        self.assertEqual(proj[0]["scope_id"], "proj-1")

    def test_recall_does_not_leak_other_scope(self) -> None:
        from src.memory.scoped_store import ScopedMemoryStore
        from src.store.database import Database

        store = ScopedMemoryStore(Database.get(self.tmp).connect())
        store.retain("personal secret", scope_type="personal", scope_id="u1", source="chat")

        results = store.recall("secret", scopes=[("personal", "u2")])

        self.assertEqual(results, [])


class TestMemoryContextBuilderScopes(unittest.TestCase):
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

    def test_build_context_includes_scoped_memory_block(self) -> None:
        from src.memory.context_builder import MemoryContextBuilder
        from src.memory.scoped_store import ScopedMemoryStore
        from src.store.database import Database

        store = ScopedMemoryStore(Database.get(self.tmp).connect())
        store.retain("技术部最近更新了考勤规则", scope_type="department", scope_id="2", source="sync")

        builder = MemoryContextBuilder(enabled=True)
        with (
            patch("src.memory.context_builder.ScopedMemoryStore", return_value=store),
            patch("src.memory.context_builder.urllib.request.urlopen", side_effect=RuntimeError("skip remote")),
        ):
            text = builder.build_context("考勤规则", scopes=[("department", "2")])

        self.assertIn("作用域记忆", text)
        self.assertIn("技术部最近更新了考勤规则", text)
