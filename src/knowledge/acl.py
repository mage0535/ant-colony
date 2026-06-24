"""Knowledge base ACL — role resolver and permission checker.

Role hierarchy: admin > leader > member > self > everyone

Knowledge scope rules:
  organization — everyone can read, admin+leader can write
  department   — dept members can read, admin+dept-leader can write
  project      — project members can read, admin+project-members can write
  personal     — only self can read/write (admin overrides all)

Department-level permissions are scoped to SPECIFIC departments:
  - A user can only read a department KB if they belong to that department
  - A user can only write to a department KB if they lead that department
"""

from __future__ import annotations

import logging
from enum import IntEnum

logger = logging.getLogger(__name__)


class Role(IntEnum):
    everyone = 0
    self = 1
    member = 2
    leader = 3
    admin = 4


def _graph():
    from src.platform.org_graph import OrgGraphService

    return OrgGraphService()


def _is_dept_member(user_id: str, dept_id: str, platform: str = "wecom") -> bool:
    return dept_id in _graph().get_user_departments(platform, user_id)


def _is_dept_leader(user_id: str, dept_id: str, platform: str = "wecom") -> bool:
    return _graph().is_department_leader(platform, user_id, dept_id)


def _is_project_member(user_id: str, project_id: str) -> bool:
    try:
        from src.rooms.space_registry import SpaceRegistry
        from src.store.database import Database
        from src.store.task_repo import TaskRepository

        registry = SpaceRegistry(repo=TaskRepository(Database.get()))
        record = registry.get(project_id)
        return bool(record and user_id in record.members)
    except Exception:
        return False


def resolve_role(user_id: str, space_id: str = "", platform: str = "wecom") -> Role:
    if not user_id:
        return Role.everyone
    graph = _graph()
    if platform == "wecom":
        try:
            graph.sync_if_stale(platform)
        except Exception:
            logger.debug("WeCom org graph stale-sync failed", exc_info=True)
    profile = graph.get_user_profile(platform, user_id)
    if profile is None and platform == "wecom":
        try:
            graph.sync_wecom_directory()
            profile = graph.get_user_profile(platform, user_id)
        except Exception:
            profile = None
    if profile and profile.get("is_admin"):
        return Role.admin
    if profile and profile.get("leader_departments"):
        return Role.leader
    if space_id and _is_project_member(user_id, space_id):
        return Role.member
    if profile and profile.get("departments"):
        return Role.member
    return Role.self


def may_read(role: Role, owner_type: str, owner_id: str, user_id: str, platform: str = "wecom") -> bool:
    """Check whether *role* can read a knowledge entry.

    For department scope, user must be a member of that specific department.
    """
    if role >= Role.admin:
        return True
    if owner_type == "organization":
        return True
    if owner_type == "department":
        if role >= Role.member:
            return _is_dept_member(user_id, owner_id, platform) or _is_dept_leader(user_id, owner_id, platform)
        return False
    if owner_type == "project":
        return role >= Role.member and _is_project_member(user_id, owner_id)
    if owner_type == "personal":
        return role >= Role.self and (owner_id == user_id)
    return False


def may_write(role: Role, owner_type: str, owner_id: str, user_id: str, platform: str = "wecom") -> bool:
    """Check whether *role* can write/delete a knowledge entry.

    For department scope, user must be the leader of that specific department.
    """
    if role >= Role.admin:
        return True
    if owner_type == "organization":
        return role >= Role.admin
    if owner_type == "department":
        if role >= Role.leader:
            return _is_dept_leader(user_id, owner_id, platform)
        return False
    if owner_type == "project":
        return role >= Role.member and _is_project_member(user_id, owner_id)
    if owner_type == "personal":
        return role >= Role.self and (owner_id == user_id)
    return False


def visible_scopes(role: Role, user_id: str, platform: str = "wecom") -> list[tuple[str, str]]:
    """Return (owner_type, owner_id) pairs that *role* can search/read.

    An admin sees everything; a leader sees org + their departments + personal;
    a member sees org (if member) + personal; self sees personal only.
    """
    scopes: list[tuple[str, str]] = []
    if role >= Role.self:
        scopes.append(("personal", user_id))
    scopes.append(("organization", "*"))
    if role >= Role.member:
        for dept_id in _graph().get_user_departments(platform, user_id)[:20]:
            scopes.append(("department", str(dept_id)))
        try:
            from src.rooms.space_registry import SpaceRegistry
            from src.store.database import Database
            from src.store.task_repo import TaskRepository

            registry = SpaceRegistry(repo=TaskRepository(Database.get()))
            for record in registry.list_all():
                if record.space_type == "project" and user_id in record.members:
                    scopes.append(("project", record.space_id))
        except Exception:
            pass
    if role >= Role.leader:
        pass
    return scopes


def writable_scopes(role: Role, user_id: str, platform: str = "wecom") -> list[tuple[str, str]]:
    scopes: list[tuple[str, str]] = []
    if role >= Role.self:
        scopes.append(("personal", user_id))
    graph = _graph()
    if role >= Role.leader:
        for dept_id in graph.get_leader_departments(platform, user_id)[:20]:
            scopes.append(("department", str(dept_id)))
    if role >= Role.admin:
        scopes.append(("organization", "*"))
    if role >= Role.member:
        try:
            from src.rooms.space_registry import SpaceRegistry
            from src.store.database import Database
            from src.store.task_repo import TaskRepository

            registry = SpaceRegistry(repo=TaskRepository(Database.get()))
            for record in registry.list_all():
                if record.space_type == "project" and user_id in record.members:
                    scopes.append(("project", record.space_id))
        except Exception:
            pass
    return _dedupe_scopes(scopes)


def default_write_scope(role: Role, user_id: str, platform: str = "wecom") -> tuple[str, str]:
    scopes = writable_scopes(role, user_id, platform)
    priority = ("organization", "department", "project", "personal") if role >= Role.admin else ("department", "project", "personal")
    for owner_type in priority:
        for scope in scopes:
            if scope[0] == owner_type:
                return scope
    return ("personal", user_id)


def _dedupe_scopes(scopes: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    result: list[tuple[str, str]] = []
    for scope in scopes:
        if scope in seen:
            continue
        seen.add(scope)
        result.append(scope)
    return result
