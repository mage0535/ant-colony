from __future__ import annotations

import json

from src.knowledge.company_guides import import_company_guides
from src.knowledge.repository_factory import build_knowledge_repository


def main() -> int:
    repo = build_knowledge_repository()
    entries = import_company_guides(repo)
    payload = {
        "imported": len(entries),
        "entries": [{"id": item.id, "title": item.metadata.get("title", ""), "owner_type": item.owner_type.value} for item in entries],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
