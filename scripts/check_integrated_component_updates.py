from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.request
from typing import Any


def _fetch_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "ant-colony-update-audit/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _run(cmd: list[str]) -> tuple[bool, str]:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    except Exception as exc:
        return False, str(exc)
    text = (result.stdout or result.stderr or "").strip()
    return result.returncode == 0, text


def _officecli_report() -> dict[str, Any]:
    binary = "/usr/local/bin/officecli"
    installed = shutil.which(binary) is not None or os.path.isfile(binary)
    ok, current = _run([binary, "--version"]) if installed else (False, "")
    latest_version = None
    error = None
    try:
        latest = _fetch_json("https://api.github.com/repos/iOfficeAI/OfficeCLI/releases/latest")
        latest_version = str(latest.get("tag_name") or "").lstrip("v")
    except Exception as exc:
        error = str(exc)
    return {
        "name": "OfficeCLI",
        "installed": installed,
        "current_version": current if ok else None,
        "latest_version": latest_version,
        "update_available": bool(installed and latest_version and current and current.strip() != latest_version),
        "source": "https://github.com/iOfficeAI/OfficeCLI/releases/latest",
        "error": error,
    }


def _stirling_report() -> dict[str, Any]:
    latest_version = None
    error = None
    try:
        latest = _fetch_json("https://api.github.com/repos/Stirling-Tools/Stirling-PDF/releases/latest")
        latest_version = str(latest.get("tag_name") or "")
    except Exception as exc:
        error = str(exc)
    return {
        "name": "Stirling-PDF",
        "configured_image": "stirlingtools/stirling-pdf:v2.14.1",
        "latest_version": latest_version,
        "update_available": latest_version not in {None, "", "v2.14.1"},
        "source": "https://github.com/Stirling-Tools/Stirling-PDF/releases/latest",
        "error": error,
    }


def _ocrmypdf_report() -> dict[str, Any]:
    installed = shutil.which("ocrmypdf") is not None
    ok, current = _run(["ocrmypdf", "--version"]) if installed else (False, "")
    latest_version = None
    error = None
    try:
        latest = _fetch_json("https://pypi.org/pypi/ocrmypdf/json")
        latest_version = str(latest.get("info", {}).get("version") or "")
    except Exception as exc:
        error = str(exc)
    return {
        "name": "OCRmyPDF",
        "installed": installed,
        "current_version": current if ok else None,
        "latest_version": latest_version,
        "update_available": bool(installed and latest_version and current and current.strip() != latest_version),
        "source": "https://pypi.org/pypi/ocrmypdf/json",
        "error": error,
    }


def _searxng_report() -> dict[str, Any]:
    return {
        "name": "SearXNG",
        "configured_image": "ghcr.io/searxng/searxng:latest",
        "latest_channel": "latest",
        "update_strategy": "docker pull ghcr.io/searxng/searxng:latest && docker compose up -d",
        "source": "https://github.com/searxng/searxng",
    }


def build_report() -> dict[str, Any]:
    components = [
        _officecli_report(),
        _stirling_report(),
        _ocrmypdf_report(),
        _searxng_report(),
    ]
    return {"components": components}


def main() -> int:
    print(json.dumps(build_report(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
