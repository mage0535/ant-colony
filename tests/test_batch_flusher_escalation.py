from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


class TestBatchFlusherEscalation(unittest.TestCase):
    def test_department_leader_escalation_falls_back_to_admin(self) -> None:
        from src.orchestrator.batch_flusher import BatchFlusher

        repo = MagicMock()
        task = type("Task", (), {"id": "t1", "project_id": "dept-2", "assignee_user_id": None})()
        repo.get_task.return_value = task
        flusher = BatchFlusher(MagicMock(), {}, MagicMock(), task_repo=repo)

        fake_record = type("Record", (), {"metadata": {"dept_id": "2"}})()
        fake_registry = MagicMock()
        fake_registry.get.return_value = fake_record
        fake_graph = MagicMock()
        fake_graph.get_department_leader_ids.return_value = []
        fake_graph.get_admin_ids.return_value = ["u-admin"]

        with (
            patch("src.rooms.space_registry.SpaceRegistry", return_value=fake_registry),
            patch("src.platform.org_graph.OrgGraphService", return_value=fake_graph),
            patch("src.orchestrator.batch_flusher.send_text", return_value=True) as mock_send,
        ):
            flusher._notify_department_leaders(task, "需要处理")

        mock_send.assert_called_with("u-admin", "[任务升级提醒] 需要处理")
