from __future__ import annotations
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch


class TestOrgGraphService(unittest.TestCase):
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

    def test_upsert_and_resolve_user_roles(self) -> None:
        from src.platform.org_graph import OrgGraphService

        graph = OrgGraphService(db_path=self.tmp)
        graph.upsert_department("wecom", "1", "公司", "")
        graph.upsert_department("wecom", "2", "技术部", "1")
        graph.upsert_user("wecom", "u-admin", "管理员")
        graph.replace_user_memberships("wecom", "u-admin", [("2", True, True)])

        self.assertTrue(graph.is_admin("wecom", "u-admin"))
        self.assertTrue(graph.is_department_leader("wecom", "u-admin", "2"))
        self.assertEqual(graph.get_user_departments("wecom", "u-admin"), ["2"])

    def test_find_user_by_name_prefers_department_member(self) -> None:
        from src.platform.org_graph import OrgGraphService

        graph = OrgGraphService(db_path=self.tmp)
        graph.upsert_department("wecom", "2", "技术部", "1")
        graph.upsert_department("wecom", "3", "市场部", "1")
        graph.upsert_user("wecom", "u-tech", "张三")
        graph.upsert_user("wecom", "u-sales", "张三")
        graph.replace_user_memberships("wecom", "u-tech", [("2", False, False)])
        graph.replace_user_memberships("wecom", "u-sales", [("3", False, False)])

        self.assertEqual(graph.find_user_by_name("wecom", "张三", dept_id="2"), "u-tech")

    def test_sync_wecom_directory_populates_departments_and_members(self) -> None:
        from src.platform.org_graph import OrgGraphService

        graph = OrgGraphService(db_path=self.tmp)
        fake_departments = [{"id": 1, "name": "公司", "parentid": 0}, {"id": 2, "name": "技术部", "parentid": 1}]
        fake_users = [
            {"userid": "u1", "name": "张三", "department": [2], "is_leader_in_dept": [1]},
            {"userid": "u2", "name": "李四", "department": [2], "is_leader_in_dept": [0]},
        ]
        with patch("src.platform.org_graph._get", side_effect=[{"department": fake_departments}, {"userlist": fake_users}]), patch(
            "src.platform.org_graph.get_admin_ids", return_value={"u1"}
        ):
            summary = graph.sync_wecom_directory()

        self.assertEqual(summary["departments"], 2)
        self.assertEqual(summary["users"], 2)
        self.assertTrue(graph.is_admin("wecom", "u1"))
        self.assertEqual(sorted(graph.get_department_members("wecom", "2")), ["u1", "u2"])

    def test_org_graph_write_retries_transient_database_lock(self) -> None:
        from src.platform.org_graph import OrgGraphService

        class FakeConnection:
            def __init__(self) -> None:
                self.execute_count = 0
                self.rollback_count = 0
                self.commit_count = 0

            def execute(self, *args, **kwargs):
                self.execute_count += 1
                if self.execute_count == 1:
                    raise sqlite3.OperationalError("database is locked")
                return None

            def rollback(self):
                self.rollback_count += 1

            def commit(self):
                self.commit_count += 1

        graph = OrgGraphService(db_path=self.tmp)
        fake = FakeConnection()
        graph._conn = fake  # type: ignore[assignment]

        with patch("src.platform.org_graph.time.sleep", return_value=None):
            graph.upsert_department("wecom", "1", "公司", "")

        self.assertEqual(fake.rollback_count, 1)
        self.assertEqual(fake.commit_count, 1)
        self.assertEqual(fake.execute_count, 2)
