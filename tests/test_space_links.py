from __future__ import annotations
import os
import tempfile
import unittest


class TestSpaceLinks(unittest.TestCase):
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

    def test_link_spaces_persists_metadata(self) -> None:
        from src.rooms.space_registry import SpaceRegistry
        from src.store.database import Database
        from src.store.task_repo import TaskRepository

        registry = SpaceRegistry(repo=TaskRepository(Database.get(self.tmp)))
        registry.register("proj-1", name="项目一")
        registry.register("dept-2", name="技术部", members=["u1"])
        registry.link_spaces("proj-1", "dept-2")

        self.assertEqual(registry.get_linked_spaces("proj-1"), ["dept-2"])
