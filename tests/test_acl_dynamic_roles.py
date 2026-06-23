from __future__ import annotations
import os
import tempfile
import unittest


class TestAclDynamicRoles(unittest.TestCase):
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

    def test_resolve_role_uses_dynamic_org_graph(self) -> None:
        from src.knowledge.acl import Role, resolve_role
        from src.platform.org_graph import OrgGraphService

        graph = OrgGraphService(db_path=self.tmp)
        graph.upsert_department("wecom", "2", "技术部", "1")
        graph.upsert_user("wecom", "u-leader", "张三")
        graph.replace_user_memberships("wecom", "u-leader", [("2", True, False)])

        self.assertEqual(resolve_role("u-leader", platform="wecom"), Role.leader)

    def test_project_read_write_requires_space_membership(self) -> None:
        from src.knowledge.acl import Role, may_read, may_write
        from src.rooms.space_registry import SpaceRegistry
        from src.store.database import Database
        from src.store.task_repo import TaskRepository

        registry = SpaceRegistry(repo=TaskRepository(Database.get(self.tmp)))
        registry.register("proj-1", name="项目一", space_type="project", members=["u-member"])

        self.assertTrue(may_read(Role.member, "project", "proj-1", "u-member"))
        self.assertFalse(may_read(Role.member, "project", "proj-1", "u-other"))
        self.assertTrue(may_write(Role.member, "project", "proj-1", "u-member"))
        self.assertFalse(may_write(Role.member, "project", "proj-1", "u-other"))
