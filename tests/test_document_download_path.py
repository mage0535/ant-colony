from __future__ import annotations
import tempfile
import unittest
from pathlib import Path


class TestDocumentDownloadPath(unittest.TestCase):
    def test_resolve_document_download_path_allows_file_inside_documents_dir(self) -> None:
        from src.web.document_paths import resolve_document_download_path

        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir)
            target = docs_dir / "report.docx"
            target.write_text("ok", encoding="utf-8")

            resolved = resolve_document_download_path(str(docs_dir), "report.docx")

            self.assertEqual(Path(resolved), target.resolve())

    def test_resolve_document_download_path_rejects_absolute_path_escape(self) -> None:
        from src.web.document_paths import resolve_document_download_path

        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir)
            outside = docs_dir.parent / "outside.txt"
            outside.write_text("secret", encoding="utf-8")
            self.addCleanup(lambda: outside.unlink(missing_ok=True))

            with self.assertRaises(FileNotFoundError):
                resolve_document_download_path(str(docs_dir), str(outside))

    def test_resolve_document_download_path_rejects_parent_traversal(self) -> None:
        from src.web.document_paths import resolve_document_download_path

        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir)
            outside = docs_dir.parent / "outside.txt"
            outside.write_text("secret", encoding="utf-8")
            self.addCleanup(lambda: outside.unlink(missing_ok=True))

            with self.assertRaises(FileNotFoundError):
                resolve_document_download_path(str(docs_dir), "../outside.txt")
