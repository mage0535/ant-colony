from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from src.gateway.wecom_outbound import send_file, send_file_card, send_text
from src.platform.api_wecom import WeComClient


def pick_probe_user() -> str:
    explicit = os.environ.get("WECOM_PROBE_USER_ID", "").strip()
    if explicit:
        return explicit
    client = WeComClient()
    admin_ids = client.get_admin_userids()
    if admin_ids:
        return sorted(admin_ids)[0]
    leader_ids = client.get_department_leader_ids()
    if leader_ids:
        return sorted(leader_ids)[0]
    return ""


def validate_outbound_flow(probe_file_path: str = "") -> dict[str, Any]:
    target = pick_probe_user()
    if not target:
        return {"configured": False, "reason": "no probe target user found"}

    if not probe_file_path:
        tmpdir = tempfile.mkdtemp(prefix="wecom-probe-")
        probe_path = Path(tmpdir) / "probe.txt"
    else:
        probe_path = Path(probe_file_path)
        probe_path.parent.mkdir(parents=True, exist_ok=True)
    probe_path.write_text("Ant Colony WeCom outbound probe", encoding="utf-8")

    download_url = (
        (os.environ.get("ANT_COLONY_DOCUMENT_BASE_URL") or "http://127.0.0.1:18092").rstrip("/")
        + "/api/v1/documents/probe.txt"
    )
    report = {
        "configured": True,
        "target_user": target,
        "text": {"ok": send_text(target, "Ant Colony text probe")},
        "file_card": {"ok": send_file_card(target, "probe.txt", download_url)},
        "file_send": {"ok": send_file(target, str(probe_path))},
    }
    return report


def outbound_flow_ok(report: dict[str, Any]) -> bool:
    return bool(
        report.get("configured")
        and report.get("text", {}).get("ok")
        and report.get("file_card", {}).get("ok")
        and report.get("file_send", {}).get("ok")
    )


def main() -> int:
    report = validate_outbound_flow()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if outbound_flow_ok(report) else 1


if __name__ == "__main__":
    raise SystemExit(main())
