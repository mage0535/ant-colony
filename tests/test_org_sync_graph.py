from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch


class TestOrgSyncGraph(unittest.TestCase):
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

    def test_sync_all_registers_department_spaces_with_members_and_metadata(self) -> None:
        from src.orchestrator.org_sync import OrgSynchronizer
        from src.platform.org_graph import OrgGraphService
        from src.rooms.space_registry import SpaceRegistry
        from src.store.database import Database
        from src.store.task_repo import TaskRepository

        graph = OrgGraphService(db_path=self.tmp)
        with (
            patch.object(graph, "sync_wecom_directory", return_value={"departments": 1, "users": 2}),
            patch.object(graph, "get_department_members", return_value=["u1", "u2"]),
            patch("src.platform.org_graph.OrgGraphService", return_value=graph),
            patch.object(OrgSynchronizer, "fetch_departments", return_value=[{"id": 2, "name": "技术部", "parentid": 1}]),
            patch.object(OrgSynchronizer, "fetch_users", return_value=[{"userid": "u1", "department": [2]}, {"userid": "u2", "department": [2]}]),
        ):
            registry = SpaceRegistry(repo=TaskRepository(Database.get(self.tmp)))
            summary = OrgSynchronizer(space_registry=registry).sync_all()

        record = registry.get("dept-2")
        self.assertEqual(summary["graph"]["users"], 2)
        self.assertIsNotNone(record)
        self.assertEqual(record.members, ["u1", "u2"])
        self.assertEqual(record.metadata["platform"], "wecom")
        self.assertEqual(record.metadata["dept_id"], "2")

    def test_public_org_sync_keeps_graph_success_when_compatibility_sync_fails(self) -> None:
        from src.web import dashboard

        class FakeGraph:
            def sync_wecom_directory(self):
                return {"departments": 1, "users": 2}

        class FakeSyncer:
            seen_sync_graph: bool | None = None

            def __init__(self, *args, **kwargs):
                pass

            def sync_all(self, *, sync_graph: bool = True):
                FakeSyncer.seen_sync_graph = sync_graph
                raise RuntimeError("legacy registry busy")

        with (
            patch("src.platform.org_graph.OrgGraphService", return_value=FakeGraph()),
            patch("src.orchestrator.org_sync.OrgSynchronizer", FakeSyncer),
            patch("src.web.dashboard.get_space_registry", return_value=object()),
        ):
            result = dashboard.sync_organization()

        self.assertFalse(FakeSyncer.seen_sync_graph)
        self.assertTrue(result["synced"])
        self.assertEqual(result["graph"]["users"], 2)
        self.assertFalse(result["compatibility_ok"])
        self.assertIn("legacy registry busy", result["compatibility"]["error"])
