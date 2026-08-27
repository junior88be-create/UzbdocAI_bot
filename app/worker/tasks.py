"""Celery tasks: document processing pipeline + scheduled cleanup.

Each task wraps async application code with asyncio.run() since Celery
workers are synchronous by default. Progress is written to the
ProcessingJob row in Postgres; the bot process polls it to update the
Telegram message (see app/bot/handlers/conversion.py).
"""

from __future__ import annotations

import asyncio
import logging

from celery import shared_task

from app.config.settings import get_settings
from app.database.database import get_session
from app.database.models import DocumentStatus
from app.database.models import OutputFormat as DBOutputFormat
from app.database.repositories import (
    DocumentRepository,
    GeneratedFileRepository,
    ProcessingJobRepository,
)
from app.schemas.extraction import DocumentResult
from app.services import docx_service, excel_service, markdown_service
from app.services.document_service import DocumentProcessingError, get_document_service
from app.services.gemini_service import GeminiServiceError
from app.services.pdf_service import PdfProcessingError
from app.utils import files
from app.utils.security import FileValidationError

# Importing celery_app (not just referencing it) is required here, not
# optional: @shared_task binds to Celery's "current app" proxy, which falls
# back to an unconfigured default Celery() instance (broker
# amqp://guest@localhost//) until a real Celery(...) app has been
# instantiated in the process. The worker gets that for free via `celery -A
# app.worker.celery_app`, but the bot process only ever does `from
# app.worker.tasks import process_document_task` - without this import,
# .delay() calls from the bot silently try to talk AMQP/RabbitMQ instead of
# the configured Redis broker and fail with a connection error.
from app.worker.celery_app import celery_app  # noqa: F401

logger = logging.getLogger(__name__)

_FORMAT_TO_DB = {
    "docx": DBOutputFormat.DOCX,
    "xlsx": DBOutputFormat.XLSX,
    "md": DBOutputFormat.MARKDOWN,
}

_KNOWN_FAILURE_TYPES = (
    DocumentProcessingError,
    GeminiServiceError,
    PdfProcessingError,
    FileValidationError,
)


@shared_task(name="process_document", bind=True, max_retries=0)
def process_document_task(
    self,
    document_id: str,
    job_id: str,
    requested_format: str,
    auto_confirm_review: bool = False,
) -> None:
    asyncio.run(_process_document_async(document_id, job_id, requested_format, auto_confirm_review))


@shared_task(name="cleanup_expired_files")
def cleanup_expired_files_task() -> None:
    from app.services.cleanup_service import run_cleanup

    asyncio.run(run_cleanup())


async def _process_document_async(
    document_id: str,
    job_id: str,
    requested_format: str,
    auto_confirm_review: bool = False,
) -> None:
    async with get_session() as session:
        job_repo = ProcessingJobRepository(session)
        doc_repo = DocumentRepository(session)
        document = await doc_repo.get(document_id)
        if document is None:
            logger.error("process_document_task: document %s not found", document_id)
            return
        await job_repo.mark_running(job_id)
        await doc_repo.update_status(document_id, DocumentStatus.PROCESSING)

    try:
        structured_result = await _get_or_build_structured_result(document_id, job_id)
    except _KNOWN_FAILURE_TYPES as exc:
        await _fail(document_id, job_id, str(exc))
        return
    except Exception:
        logger.exception("Unexpected error processing document %s", document_id)
        await _fail(document_id, job_id, "Ҳужжатни қайта ишлашда кутилмаган хатолик юз берди.")
        return

    if structured_result.has_uncertain_content() and not auto_confirm_review:
        async with get_session() as session:
            doc_repo = DocumentRepository(session)
            document = await doc_repo.get(document_id)
        if document is not None and not document.review_confirmed:
            # OCR review step: pause here instead of generating output files.
            # The bot shows the flagged items; process_document_task is
            # dispatched again (as a fresh job) once the user confirms - see
            # app/bot/handlers/review.py. The structured result stays cached,
            # so re-dispatching never re-calls Gemini.
            async with get_session() as session:
                job_repo = ProcessingJobRepository(session)
                await job_repo.mark_needs_review(job_id)
            return

    try:
        await _generate_outputs(document_id, structured_result, requested_format)
    except Exception:
        logger.exception("Output generation failed for document %s", document_id)
        await _fail(document_id, job_id, "Сўралган файл(лар)ни яратиб бўлмади.")
        return

    async with get_session() as session:
        job_repo = ProcessingJobRepository(session)
        await job_repo.mark_succeeded(job_id)


async def _fail(document_id: str, job_id: str, message: str) -> None:
    async with get_session() as session:
        job_repo = ProcessingJobRepository(session)
        doc_repo = DocumentRepository(session)
        await job_repo.mark_failed(job_id, message)
        await doc_repo.update_status(document_id, DocumentStatus.FAILED, error_message=message)


async def _get_or_build_structured_result(document_id: str, job_id: str) -> DocumentResult:
    settings = get_settings()
    document_service = get_document_service()

    async with get_session() as session:
        doc_repo = DocumentRepository(session)
        document = await doc_repo.get(document_id)
        if document is None:
            raise DocumentProcessingError("Ҳужжат топилмади")
        cached_path = document.structured_data_path
        stored_filename = document.stored_filename
        mime_type = document.mime_type
        original_filename = document.original_filename
        content_hash = document.content_hash

    if cached_path:
        try:
            result = document_service.load_result(cached_path)
        except Exception:
            # A cached result written before a schema change (e.g. a new
            # validation constraint) can fail to (re)validate here even
            # though it was valid when it was written. Treat that as a
            # cache miss rather than a hard failure - fall through and
            # re-extract, rather than stranding the user on an error for a
            # document that used to work.
            logger.warning(
                "Cached structured result for document %s failed to load - re-extracting", document_id
            )
        else:
            logger.info("Reusing cached structured result for document %s (no Gemini call)", document_id)
            return result

    absolute_path = files.absolute_path_for(f"uploads/{stored_filename}")
    file_bytes = absolute_path.read_bytes()

    async def on_progress(stage: str, current: int | None, total: int | None) -> None:
        async with get_session() as session:
            job_repo = ProcessingJobRepository(session)
            await job_repo.update_progress(job_id, stage, current, total)

    result = await document_service.process(
        file_bytes=file_bytes,
        mime_type=mime_type,
        filename=original_filename,
        max_pages=settings.max_pdf_pages,
        on_progress=on_progress,
    )

    relative_path = document_service.save_result(content_hash, result)
    async with get_session() as session:
        doc_repo = DocumentRepository(session)
        await doc_repo.set_structured_result(
            document_id,
            structured_data_path=relative_path,
            document_type=result.document_type,
            language=result.language,
            page_count=result.pages,
            has_uncertain_content=result.has_uncertain_content(),
            search_text=result.to_search_text(),
        )
    return result


def _resolve_formats(requested_format: str, result: DocumentResult) -> list[str]:
    if requested_format == "all":
        return ["docx", "xlsx", "md"]
    if requested_format == "auto":
        formats = ["docx", "md"]
        if result.tables:
            formats.append("xlsx")
        return formats
    return [requested_format]


async def _generate_outputs(document_id: str, result: DocumentResult, requested_format: str) -> None:
    settings = get_settings()
    formats = _resolve_formats(requested_format, result)

    async with get_session() as session:
        doc_repo = DocumentRepository(session)
        document = await doc_repo.get(document_id)
        if document is None:
            raise DocumentProcessingError("Ҳужжат топилмади")
        original_filename = document.original_filename

    for fmt in formats:
        db_format = _FORMAT_TO_DB[fmt]

        async with get_session() as session:
            gen_repo = GeneratedFileRepository(session)
            existing = await gen_repo.find_existing(document_id, db_format)
        if existing is not None:
            continue  # already generated and not expired - avoid duplicate work

        if fmt == "docx":
            relative_path, absolute_path = files.reserve_output_path("outputs", ".docx")
            docx_service.generate_docx(result, original_filename, str(absolute_path))
        elif fmt == "xlsx":
            relative_path, absolute_path = files.reserve_output_path("outputs", ".xlsx")
            excel_service.generate_xlsx(result, str(absolute_path))
        elif fmt == "md":
            relative_path, absolute_path = files.reserve_output_path("outputs", ".md")
            markdown_text = markdown_service.generate_markdown(result, original_filename)
            absolute_path.write_text(markdown_text, encoding="utf-8")
        else:
            continue

        file_size = absolute_path.stat().st_size
        async with get_session() as session:
            gen_repo = GeneratedFileRepository(session)
            await gen_repo.create(
                document_id=document_id,
                format=db_format,
                path=relative_path,
                file_size=file_size,
                retention_hours=settings.file_retention_hours,
            )
