"""Tests for local (non-Gemini) PDF inspection and rendering."""

from __future__ import annotations

from unittest.mock import patch

import pymupdf as fitz
import pytest

from app.schemas.document import SourceKind
from app.services.pdf_service import (
    PdfProcessingError,
    _looks_garbled,
    inspect_pdf,
    render_pages_to_images,
)


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


def test_looks_garbled_accepts_clean_uzbek_cyrillic_text():
    text = (
        "Тошкент шахар суди жиноят ишлари бўйича судлов хайъати "
        "2024 йил 15 апрель куни очиқ суд мажлисида қуйидагиларни аниқлади."
    )
    assert _looks_garbled(text) is False


def test_looks_garbled_detects_broken_font_encoding():
    # Real excerpt (garbled) from a court ruling PDF whose embedded font
    # subset had no proper ToUnicode CMap - PyMuPDF pulled the wrong
    # Unicode code point per glyph even though the page renders as normal
    # Uzbek Cyrillic text visually. Note the fused Latin/digit artifacts
    # inside otherwise-Cyrillic tokens: "жtиноят", "2О24" (Cyrillic О, not
    # zero), "k.М" - a human or Gemini Vision reading the rendered page
    # would see completely normal text.
    text = (
        "тошкЕнт шлцлр суди жtиноят ишлдри Буйичл судлов цлЙълти "
        "тлФтиш инстлнциясининг лхtрими 2О24 йил 15 апрелъ куни"
    )
    assert _looks_garbled(text) is True


def test_looks_garbled_ignores_isolated_latin_words_in_mixed_text():
    # A single whole-word Latin/roman-numeral token (not fused *inside* a
    # Cyrillic token) is normal bilingual/legal-citation text, not garbling.
    text = "судлов хайъати судьялари К.Мирсафаев ва VI бўлимдан иборат таркибда"
    assert _looks_garbled(text) is False


def test_inspect_pdf_routes_garbled_digital_text_page_to_vision():
    # Regression: a PDF with a broken font encoding was classified as
    # DIGITAL_PDF purely by character count, so the garbled text layer was
    # trusted and passed straight to Gemini's text-structuring prompt
    # instead of being rendered and read via Gemini Vision. Real Cyrillic
    # text can't actually be embedded in a test PDF via PyMuPDF's default
    # (Latin-only) font, so get_text() is patched directly to return the
    # garbled sample - inspect_pdf's classification logic is what's under
    # test here, not PDF text-rendering.
    garbled = (
        "тошкЕнт шлцлр суди жtиноят ишлдри Буйичл судлов цлЙълти "
        "тлФтиш инстлнциясининг лхtрими 2О24 йил 15 апрелъ куни "
        "очиk суд мАжлисидА kуйидАгилАрни лниkлАди "
    ) * 3
    pdf_bytes = _build_digital_pdf(num_pages=1)

    with patch.object(fitz.Page, "get_text", return_value=garbled):
        inspection = inspect_pdf(pdf_bytes, max_pages=10)

    assert inspection.source_kind == SourceKind.SCANNED_PDF
    assert inspection.digital_text_pages == 0
    assert inspection.scanned_pages == 1
    assert inspection.needs_vision
    assert 1 not in inspection.extracted_text_by_page


def test_render_pages_to_images_returns_png_bytes():
    pdf_bytes = _build_digital_pdf(num_pages=2)
    images = render_pages_to_images(pdf_bytes, [1, 2])

    assert len(images) == 2
    for image_bytes in images:
        assert image_bytes[:8] == b"\x89PNG\r\n\x1a\n"
