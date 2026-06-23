from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime
from typing import Any

from src.observability.langsmith_support import configure_langsmith_env, get_langsmith_client

LOW_QUALITY_HINTS = (
    "未找到",
    "抱歉",
    "无法",
    "确实没收到",
    "提取不到文字内容",
    "请把文件里的文字贴过来",
)


def _duration_seconds(run: Any) -> float:
    start = getattr(run, "start_time", None)
    end = getattr(run, "end_time", None)
    if not start or not end:
        return 0.0
    if isinstance(start, str):
        start = datetime.fromisoformat(start.replace("Z", "+00:00"))
    if isinstance(end, str):
        end = datetime.fromisoformat(end.replace("Z", "+00:00"))
    return max((end - start).total_seconds(), 0.0)


def _extract_text(payload: Any) -> str:
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        values = []
        for value in payload.values():
            values.append(_extract_text(value))
        return " ".join(v for v in values if v)
    if isinstance(payload, list):
        return " ".join(_extract_text(item) for item in payload if item is not None)
    return str(payload)


def collect_quality_report(limit: int = 100, slow_threshold_seconds: float = 8.0) -> dict[str, Any]:
    configure_langsmith_env()
    client = get_langsmith_client()
    if client is None:
        return {"configured": False, "reason": "LANGSMITH_API_KEY missing or client init failed"}

    project = os.environ.get("LANGSMITH_PROJECT", "ant-colony")
    runs = list(client.list_runs(project_name=project, limit=limit))
    slow_runs = []
    failed_runs = []
    low_quality_candidates = []
    name_counter = Counter()

    for run in runs:
        name = getattr(run, "name", "") or ""
        duration = _duration_seconds(run)
        run_type = getattr(run, "run_type", "") or ""
        error = getattr(run, "error", None)
        outputs = getattr(run, "outputs", None)
        text_blob = _extract_text(outputs)
        name_counter[name] += 1

        if duration >= slow_threshold_seconds:
            slow_runs.append({"name": name, "run_type": run_type, "duration_seconds": round(duration, 3)})
        if error:
            failed_runs.append({"name": name, "run_type": run_type, "error": str(error)[:240]})
        if name == "generate_document" and any(hint in text_blob for hint in LOW_QUALITY_HINTS):
            low_quality_candidates.append(
                {
                    "name": name,
                    "run_type": run_type,
                    "duration_seconds": round(duration, 3),
                    "excerpt": text_blob[:240],
                }
            )

    return {
        "configured": True,
        "project": project,
        "run_count": len(runs),
        "slow_threshold_seconds": slow_threshold_seconds,
        "top_names": name_counter.most_common(15),
        "slow_runs": slow_runs[:20],
        "failed_runs": failed_runs[:20],
        "low_quality_document_runs": low_quality_candidates[:20],
    }


def main() -> int:
    print(json.dumps(collect_quality_report(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
