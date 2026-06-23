from __future__ import annotations
from pathlib import Path


def resolve_document_download_path(documents_dir: str, filename: str) -> str:
    """Resolve a downloadable document path and keep it pinned inside the documents dir."""
    docs_root = Path(documents_dir).resolve()
    candidate = (docs_root / filename).resolve()

    try:
        candidate.relative_to(docs_root)
    except ValueError as exc:
        raise FileNotFoundError(filename) from exc

    if not candidate.is_file():
        raise FileNotFoundError(filename)

    return str(candidate)
