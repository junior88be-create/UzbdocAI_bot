"""Batched Gemini Vision OCR orchestration for scanned/handwritten pages.

Pages are sent in small controlled batches (not one call per page, not the
whole document in one call) to bound both latency and per-call image token
cost, then the per-batch DocumentResult objects are merged into one.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from app.schemas.extraction import DocumentResult, EntityFields
from app.services.gemini_service import GeminiService

logger = logging.getLogger(__name__)

_BATCH_SIZE = 4  # pages per Gemini Vision call

ProgressCallback = Callable[[int, int], Awaitable[None]]


def merge_results(results: list[DocumentResult], language_hint: str | None = None) -> DocumentResult:
    if not results:
        raise ValueError("No OCR results to merge")

    merged = DocumentResult(
        document_type=results[0].document_type,
        language=language_hint or results[0].language,
        confidence=sum(r.confidence for r in results) / len(results),
        pages=max(r.pages for r in results),
    )
    entities = EntityFields()

    for result in results:
        merged.text_blocks.extend(result.text_blocks)
        merged.headings.extend(result.headings)
        merged.paragraphs.extend(result.paragraphs)
        merged.tables.extend(result.tables)
        merged.lists.extend(result.lists)
        merged.warnings.extend(result.warnings)
        for field_name in (
            "names",
            "dates",
            "document_numbers",
            "amounts",
            "addresses",
            "signatures",
            "stamps",
        ):
            getattr(entities, field_name).extend(getattr(result.entities, field_name))
        if result.metadata.title and not merged.metadata.title:
            merged.metadata.title = result.metadata.title
        if result.metadata.detected_document_type and not merged.metadata.detected_document_type:
            merged.metadata.detected_document_type = result.metadata.detected_document_type

    merged.entities = entities
    merged.metadata.page_count = merged.pages
    return merged


async def run_vision_ocr(
    gemini: GeminiService,
    pdf_bytes_renderer,
    page_numbers: list[int],
    is_handwritten_hint: bool = False,
    on_progress: ProgressCallback | None = None,
) -> DocumentResult:
    """pdf_bytes_renderer: callable(page_numbers) -> list[bytes] (PNG images).

    Kept as a callable rather than raw bytes so single-image uploads and PDF
    page batches can share this code path.
    """
    results: list[DocumentResult] = []
    total = len(page_numbers)
    done = 0

    for start in range(0, total, _BATCH_SIZE):
        batch_pages = page_numbers[start : start + _BATCH_SIZE]
        images = pdf_bytes_renderer(batch_pages)
        batch_result = await gemini.extract_from_images(
            images=images,
            page_numbers=batch_pages,
            is_handwritten_hint=is_handwritten_hint,
        )
        results.append(batch_result)
        done += len(batch_pages)
        if on_progress:
            await on_progress(done, total)

    return merge_results(results)
