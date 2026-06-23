from __future__ import annotations

import os
import tempfile
import unittest

from src.engine import AgentEngine, AgentEngineConfig
from src.models import Message


class TestProjectAssignment(unittest.TestCase):
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

    def test_heuristic_assignment_uses_named_department_member(self) -> None:
        from src.agents.project_agent import ProjectAgent
        from src.platform.org_graph import OrgGraphService
        from src.rooms.space_registry import SpaceRegistry
        from src.store.database import Database
        from src.store.task_repo import TaskRepository

        graph = OrgGraphService(db_path=self.tmp)
        graph.upsert_department("wecom", "2", "技术部", "1")
        graph.upsert_user("wecom", "u-zhang", "张三")
        graph.replace_user_memberships("wecom", "u-zhang", [("2", False, False)])

        registry = SpaceRegistry(repo=TaskRepository(Database.get(self.tmp)))
        registry.register("dept-2", name="技术部", space_type="department", members=["u-zhang"])

        engine = AgentEngine(AgentEngineConfig(model_name="test", agent_role="project", api_key=""))
        agent = ProjectAgent("dept-2", engine)
        drafts = agent.identify_tasks(
            "dept-2",
            [Message(id="m1", space_id="dept-2", sender_user_id="u-manager", content="TODO: 张三今天完成登录页修复")],
        )

        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0].assignee_user_id, "u-zhang")
