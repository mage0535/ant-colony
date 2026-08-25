from __future__ import annotations

import os
import sys


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


def main() -> int:
    try:
        import winrm
    except Exception as exc:  # pragma: no cover - depends on deployment environment
        print(f"pywinrm is not installed or cannot be imported: {exc}", file=sys.stderr)
        return 2

    host = _required_env("RATEMIN_WINRM_HOST")
    username = _required_env("RATEMIN_WINRM_USERNAME")
    password = _required_env("RATEMIN_WINRM_PASSWORD")
    task_name = os.environ.get("RATEMIN_WINRM_TASK_NAME", "AntColony-Ratemin-Collector").strip()
    transport = os.environ.get("RATEMIN_WINRM_TRANSPORT", "ntlm").strip() or "ntlm"
    scheme = os.environ.get("RATEMIN_WINRM_SCHEME", "http").strip() or "http"
    port = os.environ.get("RATEMIN_WINRM_PORT", "5985").strip() or "5985"

    endpoint = f"{scheme}://{host}:{port}/wsman"
    session = winrm.Session(endpoint, auth=(username, password), transport=transport)
    command = (
        "$ErrorActionPreference = 'Stop'; "
        f"$task = Get-ScheduledTask -TaskName '{task_name}' -ErrorAction Stop; "
        "if ($task.State -ne 'Running') { Start-ScheduledTask -TaskName $task.TaskName; 'started' } "
        "else { 'already_running' }"
    )
    result = session.run_ps(command)
    stdout = (result.std_out or b"").decode("utf-8", "replace").strip()
    stderr = (result.std_err or b"").decode("utf-8", "replace").strip()
    if stdout:
        print(stdout)
    if stderr:
        print(stderr, file=sys.stderr)
    return 0 if result.status_code == 0 else result.status_code


if __name__ == "__main__":
    raise SystemExit(main())
