from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AgentInfo:
    user_id: str
    role: str = ""
    department: str = ""
    last_active: float = 0.0
    message_count: int = 0


class AgentPool:
    """Tracks PersonalAgent instances with health and activity metadata.

    Hooks into InboundGatewayService.personal_agents to track which
    agents exist, their role info from SidecarMemory, and when they
    were last active.
    """

    def __init__(self) -> None:
        self._agents: dict[str, AgentInfo] = {}
        self._started_at = time.time()

    def register(self, user_id: str, role: str = "", department: str = "") -> AgentInfo:
        if user_id not in self._agents:
            self._agents[user_id] = AgentInfo(user_id=user_id, role=role, department=department)
            logger.info("AgentPool: registered %s", user_id)
        return self._agents[user_id]

    def record_activity(self, user_id: str) -> AgentInfo | None:
        info = self._agents.get(user_id)
        if info is None:
            info = self.register(user_id)
        info.last_active = time.time()
        info.message_count += 1
        return info

    def update_info(self, user_id: str, role: str = "", department: str = "") -> AgentInfo | None:
        info = self._agents.get(user_id)
        if info is None:
            info = self.register(user_id, role=role, department=department)
        else:
            if role:
                info.role = role
            if department:
                info.department = department
        return info

    def get(self, user_id: str) -> AgentInfo | None:
        return self._agents.get(user_id)

    def remove(self, user_id: str) -> None:
        self._agents.pop(user_id, None)
        logger.info("AgentPool: removed %s", user_id)

    def stats(self) -> dict[str, Any]:
        now = time.time()
        total = len(self._agents)
        active = sum(1 for a in self._agents.values() if now - a.last_active < 300)
        total_messages = sum(a.message_count for a in self._agents.values())
        return {
            "total_agents": total,
            "active_agents": active,
            "idle_agents": total - active,
            "total_messages_processed": total_messages,
            "uptime_seconds": round(now - self._started_at, 1),
        }

    def list_agents(self) -> list[dict[str, Any]]:
        now = time.time()
        result: list[dict[str, Any]] = []
        for info in sorted(self._agents.values(), key=lambda a: a.last_active, reverse=True):
            result.append({
                "user_id": info.user_id,
                "role": info.role,
                "department": info.department,
                "last_active_seconds_ago": round(now - info.last_active, 1) if info.last_active else None,
                "message_count": info.message_count,
                "status": "active" if (info.last_active and now - info.last_active < 300) else "idle",
            })
        return result

    def sync_from_gateway(self, agents_dict: dict[str, Any]) -> None:
        for user_id, agent in agents_dict.items():
            role = ""
            dept = ""
            try:
                mem = agent.memory.load()
                role = str(mem.get("role", ""))
                dept = str(mem.get("department", ""))
            except Exception:
                pass
            self.register(user_id, role=role, department=dept)
