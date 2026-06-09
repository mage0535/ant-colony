from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(slots=True)
class ToolSpec:
    id: str
    name: str
    category: str
    risk_level: str
    allowed_roles: list[str]
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    handler: Callable[..., Any] | None = None


class FusionToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self._sources: dict[str, str] = {}

    def register(self, tool: ToolSpec, source: str) -> None:
        self._tools[tool.id] = tool
        self._sources[tool.id] = source

    def get_for_agent(self, agent_role: str) -> list[ToolSpec]:
        return [tool for tool in self._tools.values() if not tool.allowed_roles or agent_role in tool.allowed_roles]
