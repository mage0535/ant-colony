from __future__ import annotations

import json
import unittest
from unittest.mock import patch


class TestStirlingPdfProvider(unittest.TestCase):
    def test_is_configured_only_accepts_local_urls(self) -> None:
        from src.platform.stirling_pdf_provider import StirlingPdfProvider

        with patch.dict("os.environ", {"STIRLING_PDF_URL": "http://127.0.0.1:8080"}):
            self.assertTrue(StirlingPdfProvider().is_configured())

        with patch.dict("os.environ", {"STIRLING_PDF_URL": "https://example.com"}, clear=True):
            self.assertFalse(StirlingPdfProvider().is_configured())

    def test_healthcheck_returns_none_when_not_local(self) -> None:
        from src.platform.stirling_pdf_provider import StirlingPdfProvider

        with patch.dict("os.environ", {"STIRLING_PDF_URL": "https://example.com"}, clear=True):
            self.assertIsNone(StirlingPdfProvider().healthcheck())

    def test_healthcheck_returns_status_payload(self) -> None:
        from src.platform.stirling_pdf_provider import StirlingPdfProvider

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps({"status": "UP"}).encode("utf-8")

        with patch.dict("os.environ", {"STIRLING_PDF_URL": "http://127.0.0.1:8080"}, clear=True), \
             patch("urllib.request.urlopen", return_value=FakeResponse()):
            result = StirlingPdfProvider().healthcheck()

        self.assertIn('"status": "UP"', result)

    def test_merge_pdf_documents_posts_to_merge_endpoint(self) -> None:
        from src.platform.stirling_pdf_provider import StirlingPdfProvider
        import tempfile
        from pathlib import Path

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"merged-pdf"

        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "a.pdf"
            b = Path(td) / "b.pdf"
            out = Path(td) / "out.pdf"
            a.write_bytes(b"a")
            b.write_bytes(b"b")

            with patch.dict("os.environ", {"STIRLING_PDF_URL": "http://127.0.0.1:8080"}, clear=True), \
                 patch("urllib.request.urlopen", return_value=FakeResponse()) as mock_open:
                result = StirlingPdfProvider().merge_pdf_documents([str(a), str(b)], str(out))
                self.assertTrue(out.exists())
                self.assertEqual(out.read_bytes(), b"merged-pdf")

        req = mock_open.call_args.args[0]
        self.assertIn("/merge-pdfs", req.full_url)
        self.assertIn("Merged PDFs", result)

    def test_read_pdf_document_posts_to_pdf_to_text_endpoint(self) -> None:
        from src.platform.stirling_pdf_provider import StirlingPdfProvider
        import tempfile
        from pathlib import Path

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"plain text"

        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "a.pdf"
            a.write_bytes(b"a")

            with patch.dict("os.environ", {"STIRLING_PDF_URL": "http://127.0.0.1:8080"}, clear=True), \
                 patch("urllib.request.urlopen", return_value=FakeResponse()) as mock_open:
                result = StirlingPdfProvider().read_pdf_document(str(a))

        req = mock_open.call_args.args[0]
        self.assertIn("/api/v1/convert/pdf/text", req.full_url)
        self.assertEqual(result, "plain text")

    def test_compress_pdf_document_posts_to_compress_endpoint(self) -> None:
        from src.platform.stirling_pdf_provider import StirlingPdfProvider
        import tempfile
        from pathlib import Path

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"compressed-pdf"

        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "a.pdf"
            out = Path(td) / "out.pdf"
            a.write_bytes(b"a")

            with patch.dict("os.environ", {"STIRLING_PDF_URL": "http://127.0.0.1:8080"}, clear=True), \
                 patch("urllib.request.urlopen", return_value=FakeResponse()) as mock_open:
                result = StirlingPdfProvider().compress_pdf_document(str(a), str(out))
                self.assertTrue(out.exists())
                self.assertEqual(out.read_bytes(), b"compressed-pdf")

        req = mock_open.call_args.args[0]
        self.assertIn("/api/v1/misc/compress-pdf", req.full_url)
        self.assertIn("Compressed PDF", result)

    def test_watermark_pdf_document_posts_to_watermark_endpoint(self) -> None:
        from src.platform.stirling_pdf_provider import StirlingPdfProvider
        import tempfile
        from pathlib import Path

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"watermarked-pdf"

        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "a.pdf"
            out = Path(td) / "out.pdf"
            a.write_bytes(b"a")

            with patch.dict("os.environ", {"STIRLING_PDF_URL": "http://127.0.0.1:8080"}, clear=True), \
                 patch("urllib.request.urlopen", return_value=FakeResponse()) as mock_open:
                result = StirlingPdfProvider().watermark_pdf_document(str(a), "CONFIDENTIAL", str(out))
                self.assertTrue(out.exists())
                self.assertEqual(out.read_bytes(), b"watermarked-pdf")

        req = mock_open.call_args.args[0]
        self.assertIn("/add-watermark", req.full_url)
        self.assertIn("Watermarked PDF", result)

    def test_split_pdf_document_posts_to_extract_page_endpoint(self) -> None:
        from src.platform.stirling_pdf_provider import StirlingPdfProvider
        import tempfile
        from pathlib import Path

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"split-pdf"

        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "a.pdf"
            out = Path(td) / "out.pdf"
            source.write_bytes(b"a")

            with patch.dict("os.environ", {"STIRLING_PDF_URL": "http://127.0.0.1:8080"}, clear=True), \
                 patch("urllib.request.urlopen", return_value=FakeResponse()) as mock_open:
                result = StirlingPdfProvider().split_pdf_document(str(source), "1-2,4", str(out))
                self.assertTrue(out.exists())
                self.assertEqual(out.read_bytes(), b"split-pdf")

        req = mock_open.call_args.args[0]
        self.assertIn("/api/v1/general/extract-page", req.full_url)
        self.assertIn("Split PDF", result)
        self.assertIn(b'name="pageNumbers"', req.data)
        self.assertIn(b"1-2,4", req.data)

    def test_protect_pdf_document_posts_to_add_password_endpoint(self) -> None:
        from src.platform.stirling_pdf_provider import StirlingPdfProvider
        import tempfile
        from pathlib import Path

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"protected-pdf"

        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "a.pdf"
            out = Path(td) / "out.pdf"
            source.write_bytes(b"a")

            with patch.dict("os.environ", {"STIRLING_PDF_URL": "http://127.0.0.1:8080"}, clear=True), \
                 patch("urllib.request.urlopen", return_value=FakeResponse()) as mock_open:
                result = StirlingPdfProvider().protect_pdf_document(str(source), "pwd123", str(out))
                self.assertTrue(out.exists())
                self.assertEqual(out.read_bytes(), b"protected-pdf")

        req = mock_open.call_args.args[0]
        self.assertIn("/api/v1/security/add-password", req.full_url)
        self.assertIn("Protected PDF", result)
        self.assertIn(b'name="password"', req.data)
        self.assertIn(b"pwd123", req.data)

    def test_extract_pdf_images_posts_to_extract_images_endpoint(self) -> None:
        from src.platform.stirling_pdf_provider import StirlingPdfProvider
        import io
        import tempfile
        import zipfile
        from pathlib import Path

        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("page1_img1.png", b"png-data")
            zf.writestr("page2_img1.jpg", b"jpg-data")

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return archive.getvalue()

        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "a.pdf"
            out_dir = Path(td) / "images"
            source.write_bytes(b"a")

            with patch.dict("os.environ", {"STIRLING_PDF_URL": "http://127.0.0.1:8080"}, clear=True), \
                 patch("urllib.request.urlopen", return_value=FakeResponse()) as mock_open:
                result = StirlingPdfProvider().extract_pdf_images(str(source), str(out_dir))
                self.assertTrue((out_dir / "page1_img1.png").exists())
                self.assertTrue((out_dir / "page2_img1.jpg").exists())

        req = mock_open.call_args.args[0]
        self.assertIn("/api/v1/misc/extract-images", req.full_url)
        self.assertIn("Extracted 2 images", result)
