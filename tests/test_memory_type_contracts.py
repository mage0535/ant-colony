from __future__ import annotations

from typing import get_type_hints

from src.memory.cold_store import ColdKnowledgeGraph, TieredContextInjector
from src.memory.warm_store import WarmMemoryStore


def test_tiered_context_injector_type_hints_resolve() -> None:
    hints = get_type_hints(TieredContextInjector.__init__)

    assert hints["warm"] is WarmMemoryStore
    assert hints["cold"] is ColdKnowledgeGraph
