"""Knowledge base ACL — role resolver and permission checker.

Role hierarchy: admin > leader > member > self > everyone

Knowledge scope rules:
  organization — everyone can read, admin+leader can write
  department   — dept members can read, admin+dept-leader can write
  project      — project members can read, admin+project-members can write
  personal     — only self can read/write (admin overrides all)
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


def resolve_role(user_id: str, space_id: str = "") -> Role:
    """Determine the highest role for *user_id* in the given *space_id*."""
    if not user_id:
        return Role.everyone

    # Admin check — WeCom (by user ID, with DB registry fallback)
    try:
        from src.platform.api_wecom import WeComClient
        wc = WeComClient()
        admin_ids = wc.get_admin_userids()
        if user_id in admin_ids:
            return Role.admin
    except Exception:
        pass
    # WeCom DB registry fallback (since API doesn't expose admins)
    try:
        from src.platform.admin_registry import get_admin_ids
        if user_id in get_admin_ids("wecom"):
            return Role.admin
    except Exception:
        pass

    # Admin check — Feishu / DingTalk (by text match)
    try:
        from src.platform import _try_feishu, _try_dingtalk
        for client_fn in [_try_feishu, _try_dingtalk]:
            client = client_fn()
            if client is None:
                continue
            try:
                admin_data = client.get_admin_users()
                if admin_data and user_id.lower() in admin_data.lower():
                    return Role.admin
            except Exception:
                pass
    except Exception:
        pass

    # Leader check — WeCom department leader
    try:
        from src.platform.api_wecom import _get
        resp = _get("user/get", f"userid={user_id}")
        leaders = resp.get("is_leader_in_dept", [0])
        if leaders and any(l == 1 for l in leaders):
            return Role.leader
    except Exception:
        pass

    # Member check — project space membership
    if space_id:
        try:
            from src.rooms.space_registry import SpaceRegistry
            from src.store.database import Database
            from src.store.task_repo import TaskRepository
            repo = TaskRepository(Database.get())
            sr = SpaceRegistry(repo=repo)
            record = sr.get(space_id)
            if record and user_id in record.members:
                return Role.member
        except Exception:
            pass

    return Role.self


def may_read(role: Role, owner_type: str, owner_id: str, user_id: str) -> bool:
    """Check whether *role* can read a knowledge entry."""
    if role >= Role.admin:
        return True
    if owner_type == "organization":
        return True
    if owner_type == "department":
        return role >= Role.member
    if owner_type == "project":
        return role >= Role.member
    if owner_type == "personal":
        return role >= Role.self and (owner_id == user_id or role >= Role.admin)
    return False


def may_write(role: Role, owner_type: str, owner_id: str, user_id: str) -> bool:
    """Check whether *role* can write/delete a knowledge entry."""
    if role >= Role.admin:
        return True
    if owner_type == "organization":
        return role >= Role.leader
    if owner_type == "department":
        return role >= Role.leader
    if owner_type == "project":
        return role >= Role.member
    if owner_type == "personal":
        return role >= Role.self and (owner_id == user_id or role >= Role.admin)
    return False


def visible_scopes(role: Role, user_id: str) -> list[tuple[str, str]]:
    """Return (owner_type, owner_id) pairs that *role* can search/read.

    An admin sees everything; a leader sees org/dep/project/personal;
    a member sees accessible projects + personal; self sees personal only.
    """
    scopes: list[tuple[str, str]] = []
    # Everyone can see *some* org-level stuff
    if role >= Role.self:
        scopes.append(("personal", user_id))
    if role >= Role.member:
        scopes.append(("organization", "*"))
    if role >= Role.leader:
        scopes.append(("department", "*"))  # leader sees all depts
    return scopes
