from __future__ import annotations

import json
import logging
import os
import time
from collections import deque
from typing import Any

logger = logging.getLogger(__name__)

MAX_TURNS = 50
_AUTO_WARM_EVERY = 10
_AUTO_COLD_EVERY = 30


class ConversationMemory:
    """In-memory conversation buffer with file persistence."""

    def __init__(self, agent_id: str, session_id: int = 0, max_turns: int = MAX_TURNS) -> None:
        self.agent_id = agent_id
        self.session_id = session_id
        self.max_turns = max_turns
        self._turns: deque[dict[str, str]] = deque(maxlen=max_turns)

    def add(self, role: str, content: str) -> None:
        self._turns.append({"role": role, "content": content, "ts": time.time()})

    def get_context(self, max_chars: int = 4000) -> str:
        if not self._turns:
            return ""
        lines: list[str] = []
        total = 0
        # Keep most recent turns (iterate in reverse, then reverse output)
        for turn in reversed(self._turns):
            line = f"[{turn['role']}]: {turn['content']}"
            if total + len(line) > max_chars:
                skipped = len(self._turns) - len(lines)
                if skipped > 0:
                    lines.append(f"...(前 {skipped} 轮对话已省略)...")
                break
            lines.append(line)
            total += len(line)
        return "\n".join(reversed(lines))

    def clear(self) -> None:
        self._turns.clear()

    def to_dict(self) -> list[dict[str, str]]:
        return list(self._turns)

    def filename(self) -> str:
        return f"{self.agent_id}_s{self.session_id}.json"

    def save(self, base_dir: str) -> None:
        path = os.path.join(base_dir, self.filename())
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, agent_id: str, session_id: int, base_dir: str, max_turns: int = MAX_TURNS) -> ConversationMemory:
        mem = cls(agent_id, session_id, max_turns)
        path = os.path.join(base_dir, mem.filename())
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            for turn in data[-max_turns:]:
                mem._turns.append(turn)
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        return mem


class ConversationStore:
    """Multi-session conversation store per user with auto-sinking to Warm+Cold."""

    def __init__(self, save_dir: str = "./data/conversations",
                 warm_store: Any = None, cold_store: Any = None) -> None:
        self.save_dir = save_dir
        self.warm = warm_store
        self.cold = cold_store
        os.makedirs(save_dir, exist_ok=True)
        self._memories: dict[str, ConversationMemory] = {}

    def _index_path(self, agent_id: str) -> str:
        return os.path.join(self.save_dir, f"{agent_id}_index.json")

    def _read_index(self, agent_id: str) -> dict[str, Any]:
        try:
            with open(self._index_path(agent_id)) as f:
                return json.load(f)
        except:
            return {"sessions": [], "active": 0}

    def _write_index(self, agent_id: str, idx: dict[str, Any]) -> None:
        with open(self._index_path(agent_id), "w") as f:
            json.dump(idx, f, ensure_ascii=False, indent=2)

    def get(self, agent_id: str) -> ConversationMemory:
        if agent_id not in self._memories:
            idx = self._read_index(agent_id)
            active = idx.get("active", 0)
            self._memories[agent_id] = ConversationMemory.load(agent_id, active, self.save_dir)
        return self._memories[agent_id]

    def new_session(self, agent_id: str) -> int:
        old = self._memories.get(agent_id)
        if old and len(old.to_dict()) > 0:
            old.save(self.save_dir)
            self.archive_session(old)
        idx = self._read_index(agent_id)
        new_id = (max(idx.get("sessions", [0])) + 1) if idx.get("sessions") else 1
        idx["sessions"].append(new_id)
        idx["active"] = new_id
        self._write_index(agent_id, idx)
        mem = ConversationMemory(agent_id, new_id)
        self._memories[agent_id] = mem
        return new_id

    def switch_session(self, agent_id: str, session_id: int) -> bool:
        idx = self._read_index(agent_id)
        if session_id not in idx.get("sessions", []):
            return False
        old = self._memories.get(agent_id)
        if old and len(old.to_dict()) > 0:
            old.save(self.save_dir)
        idx["active"] = session_id
        self._write_index(agent_id, idx)
        mem = ConversationMemory.load(agent_id, session_id, self.save_dir)
        self._memories[agent_id] = mem
        return True

    def list_sessions(self, agent_id: str) -> list[dict[str, Any]]:
        idx = self._read_index(agent_id)
        active = idx.get("active", 0)
        sessions = []
        for sid in idx.get("sessions", []):
            path = os.path.join(self.save_dir, f"{agent_id}_s{sid}.json")
            turn_count = 0
            try:
                data = json.load(open(path))
                turn_count = len(data)
            except:
                pass
            sessions.append({"id": sid, "turns": turn_count, "active": sid == active})
        return sessions

    def save_all(self) -> None:
        for agent_id, mem in self._memories.items():
            mem.save(self.save_dir)

    def record(self, agent_id: str, role: str, content: str) -> None:
        mem = self.get(agent_id)
        mem.add(role, content)
        self._auto_sink(mem)

    def archive_session(self, mem: ConversationMemory) -> None:
        """Archive full session to Warm+Cold memory layers."""
        turns = mem.to_dict()
        if len(turns) < 2:
            return
        summary = f"对话：{mem.agent_id} 会话#{mem.session_id}，共{len(turns)}轮"
        for t in turns:
            c = t.get("content", "")
            if len(c) < 15:
                continue
            if self.warm:
                self.warm.retain(c, source=f"session:{mem.agent_id}#{mem.session_id}",
                                 domain=mem.agent_id)
            if self.cold:
                self.cold.extract_and_ingest(c, domain=mem.agent_id)
        logger.info("Archived session %s#%s (%d turns)", mem.agent_id, mem.session_id, len(turns))

    def _auto_sink(self, mem: ConversationMemory) -> None:
        """Auto-sink turns to Warm+Cold at checkpoints."""
        turns = mem.to_dict()
        turn_count = len(turns)
        if turn_count % _AUTO_WARM_EVERY != 0:
            return
        batch = turns[-_AUTO_WARM_EVERY:]
        for t in batch:
            c = t.get("content", "")
            if len(c) < 15:
                continue
            if self.warm:
                self.warm.retain(c, source=f"session:{mem.agent_id}#{mem.session_id}:auto",
                                 domain=mem.agent_id)
        logger.info("Auto-sink Warm: %s#%s turn %d (%d msgs)",
                     mem.agent_id, mem.session_id, turn_count, len(batch))
        if turn_count % _AUTO_COLD_EVERY == 0:
            for t in batch:
                c = t.get("content", "")
                if len(c) < 15:
                    continue
                if self.cold:
                    self.cold.extract_and_ingest(c, domain=mem.agent_id)
            logger.info("Auto-sink Cold: %s#%s turn %d", mem.agent_id, mem.session_id, turn_count)
