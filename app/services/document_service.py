"""Top-level document processing orchestration.

Ties together pdf_service (local, free), gemini_service (paid), and
ocr_service (batched vision calls) behind one entry point used by both the
Celery worker task and tests. Also owns persistence of the structured
extraction result so repeated export requests never re-call Gemini.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from app.schemas.document import DocumentInspection, SourceKind
from app.schemas.extraction import DocumentResult
from app.services import ocr_service, pdf_service
from app.services.gemini_service import GeminiService, get_gemini_service
from app.utils import files

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str, int | None, int | None], Awaitable[None]]


class DocumentProcessingError(Exception):
    pass


class DocumentService:
    def __init__(self, gemini: GeminiService | None = None) -> None:
        self.gemini = gemini or get_gemini_service()

    def inspect(self, file_bytes: bytes, mime_type: str, max_pages: int) -> DocumentInspection:
        if mime_type == "application/pdf":
            return pdf_service.inspect_pdf(file_bytes, max_pages)
        # Single image upload behaves like a one-page scanned document.
        return DocumentInspection(
            source_kind=SourceKind.IMAGE,
            page_count=1,
            digital_text_pages=0,
            scanned_pages=1,
        )

    async def process(
        self,
        file_bytes: bytes,
        mime_type: str,
        filename: str,
        max_pages: int,
        on_progress: ProgressCallback | None = None,
    ) -> DocumentResult:
        inspection = self.inspect(file_bytes, mime_type, max_pages)

        async def _progress(stage: str, current: int | None = None, total: int | None = None) -> None:
            if on_progress:
                await on_progress(stage, current, total)

        if inspection.source_kind == SourceKind.IMAGE:
            await _progress("ocr", 0, 1)
            png_bytes = pdf_service.image_bytes_to_png(file_bytes)
            result = await self.gemini.extract_from_images(
                images=[png_bytes], page_numbers=[1], is_handwritten_hint=True
            )
            result.pages = 1
            await _progress("ocr", 1, 1)
            return result

        if inspection.source_kind == SourceKind.DIGITAL_PDF:
            await _progress("structuring", None, None)
            result = await self.gemini.extract_from_text(inspection.extracted_text_by_page, filename)
            result.pages = inspection.page_count
            return result

        if inspection.source_kind == SourceKind.SCANNED_PDF:
            page_numbers = list(range(1, inspection.page_count + 1))

            async def vision_progress(done: int, total: int) -> None:
                await _progress("ocr", done, total)

            result = await ocr_service.run_vision_ocr(
                self.gemini,
                lambda pages: pdf_service.render_pages_to_images(file_bytes, pages),
                page_numbers,
                is_handwritten_hint=True,
                on_progress=vision_progress,
            )
            result.pages = inspection.page_count
            return result

        # MIXED_PDF: some pages have a text layer, some don't.
        digital_pages = sorted(inspection.extracted_text_by_page.keys())
        scanned_pages = [
            p for p in range(1, inspection.page_count + 1) if p not in inspection.extracted_text_by_page
        ]

        sub_results: list[DocumentResult] = []

        if digital_pages:
            await _progress("structuring", None, None)
            sub_results.append(
                await self.gemini.extract_from_text(inspection.extracted_text_by_page, filename)
            )

        if scanned_pages:

            async def vision_progress(done: int, total: int) -> None:
                await _progress("ocr", done, total)

            sub_results.append(
                await ocr_service.run_vision_ocr(
                    self.gemini,
                    lambda pages: pdf_service.render_pages_to_images(file_bytes, pages),
                    scanned_pages,
                    is_handwritten_hint=True,
                    on_progress=vision_progress,
                )
            )

        result = ocr_service.merge_results(sub_results)
        result.pages = inspection.page_count
        return result

    def save_result(self, content_hash: str, result: DocumentResult) -> str:
        return files.save_json_for_document(content_hash, result.model_dump_json())

    def load_result(self, structured_data_path: str) -> DocumentResult:
        raw_json = files.load_json_for_document(structured_data_path)
        return DocumentResult.model_validate_json(raw_json)


_service: DocumentService | None = None


def get_document_service() -> DocumentService:
    global _service
    if _service is None:
        _service = DocumentService()
    return _service
