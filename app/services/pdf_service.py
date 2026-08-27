"""PDF inspection and rendering, powered by PyMuPDF (fitz).

Cost-control entry point: inspect_pdf() decides, per page, whether a
selectable text layer exists. Pages with a real text layer are read for
free; only pages without one are flagged for a (paid) Gemini Vision call.
"""

from __future__ import annotations

import io
import logging

import pymupdf as fitz
from PIL import Image

from app.schemas.document import DocumentInspection, SourceKind

logger = logging.getLogger(__name__)

# A page is considered "digital text" if it has at least this many
# characters of extractable text - short strings are often just a stray
# watermark/page number on an otherwise scanned page.
_MIN_TEXT_CHARS_FOR_DIGITAL = 40

# Rendering resolution for pages sent to Gemini Vision. Handwriting - Uzbek
# Cyrillic/Latin especially, where diacritics like Ў/Қ/Ғ/Ҳ or the oʻ/gʻ
# apostrophe-letter are small and easily lost - benefits materially from
# higher input resolution. These were bumped up from 200 DPI / 2000px after
# the initial MVP specifically to improve handwriting fidelity; raise
# further only with awareness that it increases Gemini image-token cost.
_RENDER_DPI = 260
_MAX_IMAGE_DIMENSION = 2600  # px, downscaled to control Gemini image token cost


class PdfProcessingError(Exception):
    pass


def inspect_pdf(pdf_bytes: bytes, max_pages: int) -> DocumentInspection:
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise PdfProcessingError("PDF файли шикастланган ёки ўқиб бўлмайдигандек кўринади.") from exc

    try:
        page_count = doc.page_count
        if page_count == 0:
            raise PdfProcessingError("PDF'да бетлар йўқ.")
        if page_count > max_pages:
            raise PdfProcessingError(
                f"PDF'да {page_count} бет бор, бу {max_pages} чегарадан ошиб кетади."
            )

        digital_pages = 0
        scanned_pages = 0
        text_by_page: dict[int, str] = {}

        for index in range(page_count):
            page = doc.load_page(index)
            text = page.get_text("text").strip()
            page_number = index + 1
            if len(text) >= _MIN_TEXT_CHARS_FOR_DIGITAL:
                digital_pages += 1
                text_by_page[page_number] = text
            else:
                scanned_pages += 1

        if digital_pages == page_count:
            source_kind = SourceKind.DIGITAL_PDF
        elif digital_pages == 0:
            source_kind = SourceKind.SCANNED_PDF
        else:
            source_kind = SourceKind.MIXED_PDF

        return DocumentInspection(
            source_kind=source_kind,
            page_count=page_count,
            digital_text_pages=digital_pages,
            scanned_pages=scanned_pages,
            extracted_text_by_page=text_by_page,
        )
    finally:
        doc.close()


def render_pages_to_images(pdf_bytes: bytes, page_numbers: list[int]) -> list[bytes]:
    """Renders the given 1-based page numbers to size-capped PNG bytes."""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise PdfProcessingError("PDF файли шикастланган ёки ўқиб бўлмайдигандек кўринади.") from exc

    images: list[bytes] = []
    try:
        zoom = _RENDER_DPI / 72
        matrix = fitz.Matrix(zoom, zoom)
        for page_number in page_numbers:
            page = doc.load_page(page_number - 1)
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            png_bytes = pixmap.tobytes("png")
            images.append(_resize_if_needed(png_bytes))
        return images
    finally:
        doc.close()


def _resize_if_needed(png_bytes: bytes) -> bytes:
    with Image.open(io.BytesIO(png_bytes)) as image:
        width, height = image.size
        if max(width, height) <= _MAX_IMAGE_DIMENSION:
            return png_bytes
        scale = _MAX_IMAGE_DIMENSION / max(width, height)
        new_size = (int(width * scale), int(height * scale))
        resized = image.resize(new_size, Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        resized.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()


def image_bytes_to_png(image_bytes: bytes) -> bytes:
    """Normalizes an arbitrary JPG/PNG upload into size-capped PNG bytes."""
    with Image.open(io.BytesIO(image_bytes)) as opened:
        normalized = opened.convert("RGB")
        width, height = normalized.size
        if max(width, height) > _MAX_IMAGE_DIMENSION:
            scale = _MAX_IMAGE_DIMENSION / max(width, height)
            normalized = normalized.resize(
                (int(width * scale), int(height * scale)), Image.Resampling.LANCZOS
            )
        buffer = io.BytesIO()
        normalized.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()
