"""Tests for local (non-Gemini) PDF inspection and rendering."""

from __future__ import annotations

import pymupdf as fitz
import pytest

from app.schemas.document import SourceKind
from app.services.pdf_service import PdfProcessingError, inspect_pdf, render_pages_to_images


def _build_digital_pdf(num_pages: int = 2) -> bytes:
    doc = fitz.open()
    for i in range(num_pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"This is page {i + 1} of a digitally authored document. " * 3)
    data = doc.tobytes()
    doc.close()
    return data


def _build_scanned_pdf(num_pages: int = 2) -> bytes:
    """A PDF whose pages contain only a drawn rectangle, no text layer -
    simulating a scanned page rendered as an image."""
    doc = fitz.open()
    for _ in range(num_pages):
        page = doc.new_page()
        page.draw_rect(fitz.Rect(50, 50, 400, 500), color=(0, 0, 0), fill=(0.8, 0.8, 0.8))
    data = doc.tobytes()
    doc.close()
    return data


def test_inspect_digital_pdf_detects_text_layer():
    pdf_bytes = _build_digital_pdf(num_pages=3)
    inspection = inspect_pdf(pdf_bytes, max_pages=10)

    assert inspection.source_kind == SourceKind.DIGITAL_PDF
    assert inspection.page_count == 3
    assert inspection.digital_text_pages == 3
    assert inspection.scanned_pages == 0
    assert not inspection.needs_vision
    assert len(inspection.extracted_text_by_page) == 3
    assert "page 1" in inspection.extracted_text_by_page[1]


def test_inspect_scanned_pdf_has_no_text_layer():
    pdf_bytes = _build_scanned_pdf(num_pages=2)
    inspection = inspect_pdf(pdf_bytes, max_pages=10)

    assert inspection.source_kind == SourceKind.SCANNED_PDF
    assert inspection.digital_text_pages == 0
    assert inspection.scanned_pages == 2
    assert inspection.needs_vision


def test_inspect_mixed_pdf():
    digital = fitz.open(stream=_build_digital_pdf(1), filetype="pdf")
    scanned = fitz.open(stream=_build_scanned_pdf(1), filetype="pdf")
    merged = fitz.open()
    merged.insert_pdf(digital)
    merged.insert_pdf(scanned)
    pdf_bytes = merged.tobytes()
    merged.close()
    digital.close()
    scanned.close()

    inspection = inspect_pdf(pdf_bytes, max_pages=10)
    assert inspection.source_kind == SourceKind.MIXED_PDF
    assert inspection.digital_text_pages == 1
    assert inspection.scanned_pages == 1


def test_inspect_pdf_rejects_too_many_pages():
    pdf_bytes = _build_digital_pdf(num_pages=5)
    with pytest.raises(PdfProcessingError):
        inspect_pdf(pdf_bytes, max_pages=2)


def test_inspect_pdf_rejects_corrupt_file():
    with pytest.raises(PdfProcessingError):
        inspect_pdf(b"not a real pdf", max_pages=10)


def test_render_pages_to_images_returns_png_bytes():
    pdf_bytes = _build_digital_pdf(num_pages=2)
    images = render_pages_to_images(pdf_bytes, [1, 2])

    assert len(images) == 2
    for image_bytes in images:
        assert image_bytes[:8] == b"\x89PNG\r\n\x1a\n"
