import logging
import os
import re
from typing import List

logger = logging.getLogger(__name__)


class PdfTool:
    """PDF manipulation backed by PyMuPDF (pymupdf)."""

    def __init__(self):
        self._fitz = None

    def _lazy_import(self):
        if self._fitz is not None:
            return
        import fitz
        self._fitz = fitz

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_page_spec(spec: str, total: int) -> List[int]:
        pages = set()
        for part in spec.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                a, b = part.split("-", 1)
                start = int(a.strip())
                end = int(b.strip())
                pages.update(range(start, min(end, total - 1) + 1))
            else:
                pages.add(int(part.strip()))
        return sorted(p for p in pages if 0 <= p < total)

    @staticmethod
    def _open_doc(path: str):
        import fitz
        if not os.path.isfile(path):
            raise FileNotFoundError(f"PDF not found: {path}")
        doc = fitz.open(path)
        return doc

    # ------------------------------------------------------------------ #
    #  API
    # ------------------------------------------------------------------ #
    def read_pdf(self, path: str) -> str:
        try:
            self._lazy_import()
            doc = self._open_doc(path)
            chunks: list[str] = []
            for page_num in range(doc.page_count):
                page = doc[page_num]
                text = (page.get_text("text") or "").strip()
                if text:
                    chunks.append(f"[Page {page_num + 1}]\n{text}")
            doc.close()
            if not chunks:
                return f"No extractable text found in {path}"
            logger.info("Read text from %s (%d pages)", path, len(chunks))
            return "\n\n".join(chunks)
        except Exception as e:
            logger.exception("read_pdf failed")
            return f"Read PDF failed: {e}"

    def merge_pdfs(self, paths: List[str], output_path: str) -> str:
        try:
            self._lazy_import()
            fitz = self._fitz

            missing = [p for p in paths if not os.path.isfile(p)]
            if missing:
                return f"Files not found: {missing}"

            merged = fitz.open()
            for p in paths:
                src = fitz.open(p)
                merged.insert_pdf(src)
                src.close()

            merged.save(output_path, deflate=True)
            merged.close()
            count = len(paths)
            logger.info("Merged %d PDFs into %s", count, output_path)
            return f"Merged {count} PDFs into {output_path}"
        except Exception as e:
            logger.exception("merge_pdfs failed")
            return f"Merge failed: {e}"

    def split_pdf(self, path: str, pages: str, output_path: str) -> str:
        try:
            self._lazy_import()
            fitz = self._fitz

            doc = self._open_doc(path)
            indices = self._parse_page_spec(pages, doc.page_count)
            if not indices:
                doc.close()
                return "No valid pages specified."

            out = fitz.open()
            for idx in indices:
                out.insert_pdf(doc, from_page=idx, to_page=idx)
            out.save(output_path, deflate=True)
            out.close()
            doc.close()
            logger.info("Split %d pages from %s into %s", len(indices), path, output_path)
            return f"Split {len(indices)} pages into {output_path}"
        except Exception as e:
            logger.exception("split_pdf failed")
            return f"Split failed: {e}"

    def compress_pdf(self, path: str, output_path: str) -> str:
        try:
            self._lazy_import()
            fitz = self._fitz

            doc = self._open_doc(path)
            original = os.path.getsize(path)
            doc.save(output_path, deflate=True, garbage=4, clean=True)
            doc.close()
            compressed = os.path.getsize(output_path)
            saved = original - compressed
            logger.info("Compressed %s: %d -> %d bytes", path, original, compressed)
            return f"Compressed {path} ({original // 1024}KB -> {compressed // 1024}KB, saved {saved // 1024}KB)"
        except Exception as e:
            logger.exception("compress_pdf failed")
            return f"Compress failed: {e}"

    def add_watermark(self, path: str, watermark_text: str, output_path: str) -> str:
        try:
            self._lazy_import()
            fitz = self._fitz

            doc = self._open_doc(path)
            for page_num in range(doc.page_count):
                page = doc[page_num]
                rect = page.rect
                tw = fitz.Rect(rect.width * 0.2, rect.height * 0.45, rect.width * 0.8, rect.height * 0.55)
                page.insert_textbox(
                    tw,
                    watermark_text,
                    fontsize=48,
                    color=(0.5, 0.5, 0.5),
                    overlay=True,
                    rotate=45,
                    align=fitz.TEXT_ALIGN_CENTER,
                )
            doc.save(output_path, deflate=True)
            doc.close()
            logger.info("Watermark added to %s", output_path)
            return f"Watermark added to {output_path}"
        except Exception as e:
            logger.exception("add_watermark failed")
            return f"Watermark failed: {e}"

    def extract_images(self, path: str, output_dir: str) -> str:
        try:
            self._lazy_import()
            fitz = self._fitz

            doc = self._open_doc(path)
            os.makedirs(output_dir, exist_ok=True)
            count = 0
            for page_num in range(doc.page_count):
                page = doc[page_num]
                images = page.get_images()
                for img_idx, img in enumerate(images):
                    xref = img[0]
                    base = doc.extract_image(xref)
                    ext = base["ext"]
                    data = base["image"]
                    name = f"page{page_num+1}_img{img_idx+1}.{ext}"
                    out = os.path.join(output_dir, name)
                    with open(out, "wb") as f:
                        f.write(data)
                    count += 1
            doc.close()
            logger.info("Extracted %d images from %s to %s", count, path, output_dir)
            return f"Extracted {count} images to {output_dir}"
        except Exception as e:
            logger.exception("extract_images failed")
            return f"Extract images failed: {e}"

    def protect_pdf(self, path: str, password: str, output_path: str) -> str:
        try:
            self._lazy_import()
            fitz = self._fitz

            doc = self._open_doc(path)
            doc.save(output_path, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=password, owner_pw=password)
            doc.close()
            logger.info("PDF protected: %s", output_path)
            return f"Password-protected PDF saved to {output_path}"
        except Exception as e:
            logger.exception("protect_pdf failed")
            return f"Protect failed: {e}"


# ------------------------------------------------------------------ #
#  Module-level convenience singleton
# ------------------------------------------------------------------ #
_tool = PdfTool()

read_pdf = _tool.read_pdf
merge_pdfs = _tool.merge_pdfs
split_pdf = _tool.split_pdf
compress_pdf = _tool.compress_pdf
add_watermark = _tool.add_watermark
extract_images = _tool.extract_images
protect_pdf = _tool.protect_pdf
