from __future__ import annotations

import shutil
import subprocess


class OcrmypdfProvider:
    """Local OCRmyPDF provider for private on-prem PDF OCR."""

    def is_configured(self) -> bool:
        return shutil.which("ocrmypdf") is not None

    def healthcheck(self) -> str | None:
        if not self.is_configured():
            return None
        try:
            result = subprocess.run(
                ["ocrmypdf", "--version"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if result.returncode != 0:
                return result.stderr.strip() or "ocrmypdf unavailable"
            return result.stdout.strip()
        except Exception as exc:
            return f"OCRmyPDF healthcheck failed: {exc}"

    def ocr_pdf_document(self, path: str, output_path: str, language: str = "chi_sim+eng") -> str | None:
        if not self.is_configured():
            return None
        cmd = [
            "ocrmypdf",
            "-l",
            language,
            "--skip-text",
            path,
            output_path,
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if result.returncode != 0:
            return result.stderr.strip() or "OCR failed"
        return f"OCR completed: {output_path}"
