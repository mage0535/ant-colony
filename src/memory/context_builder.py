"""
Memory integration layer — queries Warm (Hindsight), Cold (gbrain),
and Knowledge (FTS5) layers and builds context blocks for Agent prompts.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

HINDSIGHT_URL = "http://127.0.0.1:8890"
GBRAIN_URL = "http://127.0.0.1:8787"
DASHBOARD_URL = "http://127.0.0.1:18092"


class MemoryContextBuilder:
    """Queries all memory + knowledge layers and builds a structured context block."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    def build_context(self, user_query: str, max_chars: int = 3000) -> str:
        if not self.enabled:
            return ""
        parts: list[str] = []

        # Warm layer: Hindsight
        try:
            url = f"{HINDSIGHT_URL}/v1/default/banks/hermes/memories/recall?query={urllib.request.quote(user_query)}&limit=3"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=2) as resp:
                data = json.loads(resp.read())
            memories = data.get("memories", [])
            if memories:
                lines = ["## 近期记忆 (Warm)"]
                for m in memories[:3]:
                    lines.append(f"- {m['memory'][:150]}")
                parts.append("\n".join(lines))
        except Exception:
            pass

        # Cold layer: gbrain
        try:
            payload = json.dumps({
                "method": "search",
                "params": {"query": user_query, "limit": 3},
                "id": 1,
            }).encode()
            req = urllib.request.Request(f"{GBRAIN_URL}/mcp", data=payload,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=2) as resp:
                data = json.loads(resp.read())
            results = data.get("result", [])
            if results:
                lines = ["## 知识图谱 (Cold)"]
                for r in results[:3]:
                    lines.append(f"- {r.get('title', '')}: {', '.join(r.get('tags', []))}")
                parts.append("\n".join(lines))
        except Exception:
            pass

        # Knowledge layer: FTS5
        try:
            url = f"{DASHBOARD_URL}/api/v1/knowledge/search?query={urllib.request.quote(user_query)}&limit=3"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read())
            results = data.get("results", [])
            if results:
                lines = ["## 知识库 (RAG)"]
                for r in results[:3]:
                    content = r.get("content", "")[:120]
                    tags = ", ".join(r.get("tags", [])[:3])
                    lines.append(f"- [{r.get('owner_type', '')}] {content}")
                    if tags:
                        lines[-1] += f" (标签: {tags})"
                parts.append("\n".join(lines))
        except Exception:
            pass

        if not parts:
            return ""

        combined = "\n\n".join(parts)
        if len(combined) > max_chars:
            combined = combined[:max_chars]
        return combined
