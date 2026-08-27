"""Handles format-choice button presses: dispatches a Celery processing job,
polls its progress in Postgres, edits a single status message, then
delivers the resulting file(s).

The worker process never talks to Telegram directly (see
app/worker/celery_app.py docstring) - all Telegram I/O happens here in the
bot process, driven by polling job/document state.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from app.bot.formats import EXPECTED_FORMATS, FILENAME_SUFFIX
from app.bot.handlers import review
from app.bot.keyboards.document import DocumentActionCallback
from app.bot.utils import editable_message, safe_edit_text
from app.database.database import get_session
from app.database.models import DocumentStatus, JobStatus
from app.database.models import OutputFormat as DBOutputFormat
from app.database.repositories import (
    DocumentRepository,
    GeneratedFileRepository,
    ProcessingJobRepository,
)
from app.utils import files

logger = logging.getLogger(__name__)

router = Router(name="conversion")

_POLL_INTERVAL_SECONDS = 2.0
_MAX_POLL_SECONDS = 15 * 60

_STAGE_LABELS = {
    "structuring": "🧠 AI таҳлили давом этмоқда",
    "ocr": "🔍 OCR давом этмоқда",
}


def _progress_bar(current: int, total: int, width: int = 10) -> str:
    if not total:
        return "░" * width + " 0%"
    ratio = min(max(current / total, 0.0), 1.0)
    filled = int(ratio * width)
    pct = int(ratio * 100)
    return f"{'█' * filled}{'░' * (width - filled)} {pct}%"


@router.callback_query(F.data.startswith(f"{DocumentActionCallback.PREFIX}:"))
async def handle_document_action(callback: CallbackQuery, db_user_id: str, state: FSMContext) -> None:
    await callback.answer()

    message = editable_message(callback)
    if message is None or not callback.data:
        return

    action, document_id = DocumentActionCallback.parse(callback.data)

    async with get_session() as session:
        doc_repo = DocumentRepository(session)
        document = await doc_repo.get(document_id)

    if document is None or document.user_id != db_user_id:
        await _safe_edit(message, "❌ Ҳужжат топилмади ёки энди мавжуд эмас.")
        return

    if action == "cancel":
        await _safe_edit(message, "❌ Бекор қилинди.")
        return

    if action not in EXPECTED_FORMATS:
        return

    if document.status == DocumentStatus.FAILED:
        await _safe_edit(
            message, "❌ Бу ҳужжат олдин хатолик билан тугаган эди. Илтимос, уни қайта юкланг."
        )
        return

    db_format = DBOutputFormat(action)

    async with get_session() as session:
        job_repo = ProcessingJobRepository(session)
        job = await job_repo.create(document_id, db_format)
        job_id = job.id

    from app.worker.tasks import process_document_task

    process_document_task.delay(document_id, job_id, action)

    status_text = (
        f"📄 Ҳужжат: {document.original_filename}\n"
        f"📑 Бетлар: {document.page_count or '?'}\n\n"
        "⏳ Навбатда..."
    )
    await _safe_edit(message, status_text)

    asyncio.create_task(
        _track_job(
            message=message,
            document_id=document_id,
            job_id=job_id,
            action=action,
            filename=document.original_filename,
            page_count=document.page_count or 0,
            state=state,
        )
    )


async def _track_job(
    message: Message,
    document_id: str,
    job_id: str,
    action: str,
    filename: str,
    page_count: int,
    state: FSMContext,
) -> None:
    elapsed = 0.0
    last_text = None

    try:
        while elapsed < _MAX_POLL_SECONDS:
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
            elapsed += _POLL_INTERVAL_SECONDS

            async with get_session() as session:
                job_repo = ProcessingJobRepository(session)
                job = await job_repo.get(job_id)

            if job is None:
                return

            if job.status == JobStatus.SUCCEEDED:
                if job.needs_review:
                    await review.present_review(
                        message, document_id, job_id, action, filename, page_count, state
                    )
                else:
                    await _finish_success(message, document_id, action, filename)
                return

            if job.status == JobStatus.FAILED:
                error_text = job.error_message or "Қайта ишлашда хатолик юз берди."
                await _safe_edit(message, f"❌ {error_text}")
                return

            text = _render_progress_text(
                filename, page_count, job.progress_stage, job.progress_current, job.progress_total
            )
            if text != last_text:
                await _safe_edit(message, text)
                last_text = text

        await _safe_edit(
            message, "⌛ Қайта ишлаш кутилганидан узоқ давом этмоқда. Бироздан сўнг /history орқали текширинг."
        )
    except Exception:
        logger.exception("Error while tracking job %s for document %s", job_id, document_id)


def _render_progress_text(
    filename: str,
    page_count: int,
    stage: str | None,
    current: int | None,
    total: int | None,
) -> str:
    lines = [f"📄 Ҳужжат: {filename}", f"📑 Бетлар: {page_count or '?'}", ""]
    if stage and current is not None and total:
        label = _STAGE_LABELS.get(stage, stage)
        lines.append(f"{label}\n{current}/{total} бет")
        lines.append(_progress_bar(current, total))
    elif stage:
        lines.append(_STAGE_LABELS.get(stage, stage) + "...")
    else:
        lines.append("⏳ Ишланмоқда...")
    return "\n".join(lines)


async def _finish_success(message: Message, document_id: str, action: str, filename: str) -> None:
    await _safe_edit(message, f"📄 Ҳужжат: {filename}\n\n📊 Файл(лар) яратилмоқда...")

    expected = EXPECTED_FORMATS[action]
    generated_files: list[tuple[DBOutputFormat, str]] = []

    async with get_session() as session:
        gen_repo = GeneratedFileRepository(session)
        for fmt in expected:
            existing = await gen_repo.find_existing(document_id, fmt)
            if existing is not None:
                generated_files.append((fmt, existing.path))

    sent_any = False
    for fmt, relative_path in generated_files:
        try:
            absolute_path = files.absolute_path_for(relative_path)
            data = absolute_path.read_bytes()
            base_name = filename.rsplit(".", 1)[0][:80] or "document"
            out_name = f"{base_name}{FILENAME_SUFFIX[fmt]}"
            await message.answer_document(BufferedInputFile(data, filename=out_name))
            sent_any = True
        except Exception:
            logger.exception("Failed to send generated file %s for document %s", relative_path, document_id)

    if sent_any:
        note = ""
        if action == "auto" and DBOutputFormat.XLSX not in {f for f, _ in generated_files}:
            note = "\n\nℹ️ Жадваллар аниқланмади, шунинг учун Автоматик режимда Excel яратилмади."
        await _safe_edit(message, f"✅ Тайёр: {filename}{note}")
    else:
        await _safe_edit(
            message, "❌ Қайта ишлаш тугади, лекин натижа файли топилмади. Илтимос, қайта уриниб кўринг."
        )


_safe_edit = safe_edit_text
