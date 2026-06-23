from __future__ import annotations

import tomllib
from pathlib import Path


def test_pyproject_uses_supported_setuptools_backend() -> None:
    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert config["build-system"]["build-backend"] == "setuptools.build_meta"


def test_pyproject_includes_root_and_nested_src_packages() -> None:
    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    package_patterns = config["tool"]["setuptools"]["packages"]["find"]["include"]
    assert package_patterns == ["src", "src.*"]


def test_credentials_are_excluded_from_version_control() -> None:
    ignore_rules = Path(".gitignore").read_text(encoding="utf-8").splitlines()

    assert "infra/.env*" in ignore_rules


def test_service_entrypoints_and_runtime_dependencies_are_packaged() -> None:
    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    project = config["project"]

    assert project["scripts"] == {
        "ant-colony-gateway": "run_gateway:main",
        "ant-colony-callback": "run_callback:main",
        "ant-colony-dashboard": "run_dashboard:main",
        "ant-colony-wecom-bot": "run_wecom_bot:main",
    }
    assert config["tool"]["setuptools"]["py-modules"] == [
        "run_gateway",
        "run_callback",
        "run_dashboard",
        "run_wecom_bot",
    ]
    dependency_names = {item.split(">=", 1)[0] for item in project["dependencies"]}
    assert {
        "cryptography",
        "defusedxml",
        "fastapi",
        "httpx",
        "openpyxl",
        "PyMuPDF",
        "pydantic",
        "python-docx",
        "python-multipart",
        "python-pptx",
        "qrcode",
        "requests",
        "uvicorn",
        "websockets",
    } <= dependency_names
