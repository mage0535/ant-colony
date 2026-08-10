from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from src.memory.cold_store import ColdKnowledgeGraph
from src.memory.maintenance import MemoryMaintenanceCycle
from src.memory.warm_store import WarmMemoryStore
from src.store.database import Database
from src.store.task_repo import TaskRepository


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Ant Colony memory maintenance once.")
    parser.add_argument("--space-id", default="", help="Optional single space id to process.")
    parser.add_argument("--db-path", default="", help="Optional SQLite database path.")
    parser.add_argument("--log-level", default=os.environ.get("ANT_COLONY_LOG_LEVEL", "INFO"))
    args = parser.parse_args(argv)

    logging.basicConfig(level=getattr(logging, str(args.log_level).upper(), logging.INFO))
    db = Database.get(args.db_path)
    conn = db.connect()
    cycle = MemoryMaintenanceCycle(
        repo=TaskRepository(db),
        warm_store=WarmMemoryStore(conn),
        cold_store=ColdKnowledgeGraph(conn),
    )
    result = cycle.run_cycle(space_id=args.space_id)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
