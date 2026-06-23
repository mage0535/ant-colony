from __future__ import annotations

import json
import os
from collections import Counter

from src.observability.langsmith_support import configure_langsmith_env, get_langsmith_client


def collect_run_report(limit: int = 50) -> dict:
    configure_langsmith_env()
    client = get_langsmith_client()
    if client is None:
        return {"configured": False, "reason": "LANGSMITH_API_KEY missing or client init failed"}
    project = os.environ.get("LANGSMITH_PROJECT", "ant-colony")
    runs = list(client.list_runs(project_name=project, limit=limit))
    run_types = Counter(getattr(run, "run_type", "") or "" for run in runs)
    names = Counter(getattr(run, "name", "") or "" for run in runs)
    return {
        "configured": True,
        "project": project,
        "run_count": len(runs),
        "run_types": dict(run_types),
        "top_names": names.most_common(15),
    }


def main() -> int:
    print(json.dumps(collect_run_report(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
