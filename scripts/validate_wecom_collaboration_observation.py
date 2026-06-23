from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch


def build_collaboration_report() -> dict:
    from src.knowledge.acl import may_read, may_write, resolve_role
    from src.orchestrator.batch_flusher import BatchFlusher
    from src.rooms.space_registry import SpaceRegistry
    from src.store.database import Database
    from src.store.task_repo import TaskRepository
    from src.platform.org_graph import OrgGraphService

    tmp = tempfile.mktemp(suffix=".db")
    os.environ["ANT_COLONY_DB_PATH"] = tmp
    try:
        db = Database.get(tmp)
        repo = TaskRepository(db)
        registry = SpaceRegistry(repo=repo)
        graph = OrgGraphService(tmp)

        graph.upsert_department("wecom", "dept-2", "技术部", "1")
        graph.upsert_user("wecom", "u-admin", "管理员")
        graph.upsert_user("wecom", "u-leader", "部门负责人")
        graph.upsert_user("wecom", "u-member", "项目成员")
        graph.replace_user_memberships("wecom", "u-admin", [("dept-2", False, True)])
        graph.replace_user_memberships("wecom", "u-leader", [("dept-2", True, False)])
        graph.replace_user_memberships("wecom", "u-member", [("dept-2", False, False)])

        registry.register("proj-1", name="项目一", space_type="project", members=["u-member"])
        registry.register("dept-space-2", name="技术部空间", space_type="department", members=["u-leader", "u-member"], metadata={"dept_id": "dept-2"})
        registry.link_spaces("proj-1", "dept-space-2")

        role_member = resolve_role("u-member", "proj-1")
        role_leader = resolve_role("u-leader", "")
        role_admin = resolve_role("u-admin", "")

        permission_matrix = {
            "project_member_read_project": may_read(role_member, "project", "proj-1", "u-member"),
            "project_member_write_project": may_write(role_member, "project", "proj-1", "u-member"),
            "project_member_write_department": may_write(role_member, "department", "dept-2", "u-member"),
            "department_leader_write_department": may_write(role_leader, "department", "dept-2", "u-leader"),
            "admin_write_organization": may_write(role_admin, "organization", "*", "u-admin"),
        }

        repo.create_task(title="跨群协作任务", description="需要同步", project_id="proj-1", assignee_user_id="u-member", priority="high")
        sent_messages: list[tuple[str, str]] = []
        flusher = BatchFlusher(batch_processor=None, project_agents={}, engine=None, task_repo=repo)  # type: ignore[arg-type]
        with patch("src.orchestrator.batch_flusher.send_text", side_effect=lambda user_id, text: sent_messages.append((user_id, text)) or True):
            flusher._fan_out_linked_space_notice("proj-1", "请同步关注这个项目任务")

        expected_checks = {
            "project_member_read_project": permission_matrix["project_member_read_project"] is True,
            "project_member_write_project": permission_matrix["project_member_write_project"] is True,
            "project_member_write_department_denied": permission_matrix["project_member_write_department"] is False,
            "department_leader_write_department": permission_matrix["department_leader_write_department"] is True,
            "admin_write_organization": permission_matrix["admin_write_organization"] is True,
        }

        return {
            "ok": all(expected_checks.values()),
            "linked_spaces": registry.get_linked_spaces("proj-1"),
            "permission_matrix": permission_matrix,
            "expected_checks": expected_checks,
            "fanout_count": len(sent_messages),
            "fanout_targets": [user_id for user_id, _ in sent_messages],
        }
    finally:
        try:
            Database.get(tmp).close()
        except Exception:
            pass
        Database._instances.pop(tmp, None)  # type: ignore[attr-defined]
        os.environ.pop("ANT_COLONY_DB_PATH", None)
        try:
            Path(tmp).unlink(missing_ok=True)
        except Exception:
            pass


def main() -> int:
    report = build_collaboration_report()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
