from __future__ import annotations

import json
import os

from src.observability.langsmith_support import configure_langsmith_env, ensure_langsmith_project, get_langsmith_client


def validate_langsmith_cloud() -> dict:
    configure_langsmith_env()
    client = get_langsmith_client()
    if client is None:
        return {"configured": False, "reason": "LANGSMITH_API_KEY missing or client init failed"}
    project = os.environ.get("LANGSMITH_PROJECT", "ant-colony")
    ensured = ensure_langsmith_project(project)
    projects = [p.name for p in client.list_projects(limit=20)]
    return {
        "configured": True,
        "project": project,
        "project_ready": ensured,
        "project_visible": project in projects,
    }


def main() -> int:
    print(json.dumps(validate_langsmith_cloud(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
