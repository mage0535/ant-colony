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


def langsmith_cloud_ok(report: dict) -> bool:
    return bool(report.get("configured") and report.get("project_ready") and report.get("project_visible"))


def main() -> int:
    report = validate_langsmith_cloud()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if os.environ.get("ANT_COLONY_VALIDATE_ALLOW_UNCONFIGURED", "").strip().lower() in {"1", "true", "yes"} and not report.get("configured"):
        return 0
    return 0 if langsmith_cloud_ok(report) else 1


if __name__ == "__main__":
    raise SystemExit(main())
