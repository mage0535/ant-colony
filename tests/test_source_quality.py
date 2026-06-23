from __future__ import annotations

import ast
import re
from pathlib import Path


def test_production_source_has_no_bare_except_handlers() -> None:
    bare_handlers: list[str] = []
    for path in Path("src").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                bare_handlers.append(f"{path}:{node.lineno}")

    assert bare_handlers == []


def test_production_source_has_no_literal_secrets_or_tokens() -> None:
    findings: list[str] = []
    sensitive_suffixes = ("SECRET", "TOKEN", "API_KEY", "PASSWORD")
    for path in Path("src").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                continue
            if len(value.value) < 16:
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id.upper().endswith(sensitive_suffixes):
                    findings.append(f"{path}:{node.lineno}:{target.id}")

    assert findings == []


def test_production_source_has_no_urls_with_embedded_credentials() -> None:
    findings: list[str] = []
    credential_url = re.compile(r"^[a-z][a-z0-9+.-]*://[^/:\s]+:[^@\s]+@", re.IGNORECASE)
    for path in Path("src").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and credential_url.match(node.value)
            ):
                findings.append(f"{path}:{node.lineno}")

    assert findings == []
