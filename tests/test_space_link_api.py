from __future__ import annotations

import os
import tempfile
import unittest


class TestSpaceLinkApi(unittest.TestCase):
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

    def test_link_spaces_and_list_links(self) -> None:
        from src.rooms.space_registry import SpaceRegistry
        from src.store.database import Database
        from src.store.task_repo import TaskRepository

        registry = SpaceRegistry(repo=TaskRepository(Database.get(self.tmp)))
        registry.register("proj-1", name="项目一")
        registry.register("dept-2", name="技术部")
        registry.link_spaces("proj-1", "dept-2")

        self.assertEqual(registry.get_linked_spaces("proj-1"), ["dept-2"])

    def test_dashboard_link_route_returns_linked_spaces(self) -> None:
        from src.web.dashboard import SpaceLinkRequest, link_space, list_space_links
        from src.rooms.space_registry import SpaceRegistry
        from src.store.database import Database
        from src.store.task_repo import TaskRepository
        from unittest.mock import patch

        registry = SpaceRegistry(repo=TaskRepository(Database.get(self.tmp)))
        registry.register("proj-1", name="项目一")
        registry.register("dept-2", name="技术部")

        with patch("src.web.dashboard.get_space_registry", return_value=registry):
            result = link_space(SpaceLinkRequest(source_space_id="proj-1", target_space_id="dept-2"))
            listed = list_space_links("proj-1")

        self.assertEqual(result["linked_spaces"], ["dept-2"])
        self.assertEqual(listed["linked_spaces"], ["dept-2"])
