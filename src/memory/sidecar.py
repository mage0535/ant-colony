from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class SidecarMemory:
    """File-backed key-value memory for a single agent.

    Stores structured context (role, responsibilities, preferences) as
    a JSON file in ``base_dir/<namespace>_<agent_id>.json``.
    Follows the Hot/Warm/Cold pattern — this is the Warm tier (persisted,
    file-backed, loaded on demand).
    """

    def __init__(self, agent_id: str, base_dir: str = "", namespace: str = "agent") -> None:
        self.agent_id = agent_id
        self.base_dir = base_dir or os.environ.get("ANT_COLONY_MEMORY_DIR", "./data/memory")
        self._path = os.path.join(self.base_dir, f"{namespace}_{agent_id}.json")
        self._data: dict[str, Any] = {}

    def load(self) -> dict[str, Any]:
        if self._data:
            return self._data
        try:
            if os.path.isfile(self._path):
                with open(self._path, encoding="utf-8") as f:
                    self._data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("SidecarMemory load failed for %s: %s", self.agent_id, e)
            self._data = {}
        return self._data

    def save(self) -> None:
        os.makedirs(self.base_dir, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self.save()

    def update(self, mapping: dict[str, Any]) -> None:
        self._data.update(mapping)
        self.save()

    def delete(self, key: str) -> None:
        self._data.pop(key, None)
        self.save()

    def build_context_block(self) -> str:
        """Build a knowledge context string for LLM system prompt injection."""
        data = self.load()
        if not data:
            return ""
        parts: list[str] = []
        for key in ("role", "department", "responsibilities", "preferences"):
            val = data.get(key)
            if val:
                if isinstance(val, list):
                    parts.append(val)
                else:
                    parts.append(str(val))
        if not parts:
            return ""
        return "## 你的已知上下文\n" + "\n".join(f"- {p}" for p in parts)
