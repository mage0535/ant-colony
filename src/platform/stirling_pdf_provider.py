from __future__ import annotations

import json
import io
import os
import urllib.error
import urllib.request
import uuid
import zipfile


class StirlingPdfProvider:
    """Local self-hosted Stirling-PDF provider skeleton.

    This provider is intentionally constrained to local/private deployment.
    It should not be used with public SaaS endpoints as the default document path.
    """

    def __init__(self) -> None:
        self.base_url = (os.environ.get("STIRLING_PDF_URL") or "http://127.0.0.1:8080").rstrip("/")
        self.api_key = os.environ.get("STIRLING_PDF_API_KEY", "")

    def is_configured(self) -> bool:
        return self.base_url.startswith("http://127.0.0.1") or self.base_url.startswith("http://localhost")

    def healthcheck(self) -> str | None:
        if not self.is_configured():
            return None
        last_error = "Stirling-PDF local service unavailable"
        for path in ("/api/v1/health", "/api/v1/info/status"):
            req = urllib.request.Request(f"{self.base_url}{path}", method="GET")
            if self.api_key:
                req.add_header("X-API-KEY", self.api_key)
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    payload = json.loads(resp.read().decode("utf-8", errors="replace"))
                if isinstance(payload, dict):
                    return json.dumps(payload, ensure_ascii=False)
                return str(payload)
            except urllib.error.URLError as exc:
                last_error = f"Stirling-PDF local service unavailable: {exc.reason}"
            except Exception as exc:
                last_error = f"Stirling-PDF healthcheck failed: {exc}"
        return last_error

    def merge_pdf_documents(self, paths: list[str], output_path: str) -> str | None:
        response = self._post_files("/merge-pdfs", paths)
        if response is None:
            return None
        with open(output_path, "wb") as f:
            f.write(response)
        return f"Merged PDFs into {output_path}"

    def read_pdf_document(self, path: str) -> str | None:
        response = self._post_files("/api/v1/convert/pdf/text", [path])
        if response is None:
            return None
        return response.decode("utf-8", errors="replace")

    def compress_pdf_document(self, path: str, output_path: str) -> str | None:
        response = self._post_files("/api/v1/misc/compress-pdf", [path])
        if response is None:
            return None
        with open(output_path, "wb") as f:
            f.write(response)
        return f"Compressed PDF into {output_path}"

    def watermark_pdf_document(self, path: str, watermark_text: str, output_path: str) -> str | None:
        response = self._post_files("/add-watermark", [path], fields={"watermarkText": watermark_text})
        if response is None:
            return None
        with open(output_path, "wb") as f:
            f.write(response)
        return f"Watermarked PDF into {output_path}"

    def split_pdf_document(self, path: str, pages: str, output_path: str) -> str | None:
        response = self._post_files("/api/v1/general/extract-page", [path], fields={"pageNumbers": pages})
        if response is None:
            return None
        with open(output_path, "wb") as f:
            f.write(response)
        return f"Split PDF into {output_path}"

    def protect_pdf_document(self, path: str, password: str, output_path: str) -> str | None:
        response = self._post_files("/api/v1/security/add-password", [path], fields={"password": password})
        if response is None:
            return None
        with open(output_path, "wb") as f:
            f.write(response)
        return f"Protected PDF into {output_path}"

    def extract_pdf_images(self, path: str, output_dir: str) -> str | None:
        response = self._post_files("/api/v1/misc/extract-images", [path])
        if response is None:
            return None
        os.makedirs(output_dir, exist_ok=True)
        count = 0
        with zipfile.ZipFile(io.BytesIO(response)) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                archive.extract(member, output_dir)
                count += 1
        return f"Extracted {count} images to {output_dir}"

    def _post_files(self, path: str, files: list[str], fields: dict[str, str] | None = None) -> bytes | None:
        if not self.is_configured():
            return None
        boundary = f"----ant-colony-{uuid.uuid4().hex}"
        body = bytearray()
        for key, value in (fields or {}).items():
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
            body.extend(str(value).encode("utf-8"))
            body.extend(b"\r\n")
        for item in files:
            filename = os.path.basename(item)
            with open(item, "rb") as f:
                data = f.read()
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(
                f'Content-Disposition: form-data; name="fileInput"; filename="{filename}"\r\n'.encode()
            )
            body.extend(b"Content-Type: application/pdf\r\n\r\n")
            body.extend(data)
            body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode())

        req = urllib.request.Request(f"{self.base_url}{path}", data=bytes(body), method="POST")
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        if self.api_key:
            req.add_header("X-API-KEY", self.api_key)
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()
