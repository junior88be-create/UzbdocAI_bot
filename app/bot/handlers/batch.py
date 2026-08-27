"""Batch processing: collect multiple PDF/image files, then process and
deliver all of them together as a single ZIP.

This router is registered before app.bot.handlers.document in app/main.py
so its state-filtered upload handlers (only active while a
BatchFlow.collecting state is set) take priority; outside batch mode,
uploads fall straight through to the single-document flow, unchanged.

Design: each document in a batch is processed through the exact same
per-document pipeline as a single upload (app.worker.tasks.process_document_task,
including its cost-control caching and per-document "auto format" logic) -
batching only adds a grouping layer (the Batch row + batch_id on Document)
and an aggregate-progress / ZIP-delivery layer on top. No worker changes
were needed for this feature.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from app.bot.formats import EXPECTED_FORMATS, FILENAME_SUFFIX
from app.bot.keyboards.batch import (
    BatchControlCallback,
    BatchFormatCallback,
    batch_collection_keyboard,
    batch_format_keyboard,
)
from app.bot.keyboards.main import MainMenuCallback
from app.bot.states.batch import BatchFlow
from app.bot.upload_pipeline import (
    StoredDocument,
    receive_document_upload,
    receive_photo_upload,
    store_and_inspect,
)
from app.bot.utils import editable_message, safe_edit_text
from app.config.settings import get_settings
from app.database.database import get_session
from app.database.models import BatchStatus, JobStatus
from app.database.models import OutputFormat as DBOutputFormat
from app.database.repositories import (
    BatchRepository,
    DocumentRepository,
    GeneratedFileRepository,
    ProcessingJobRepository,
)
from app.utils import files

logger = logging.getLogger(__name__)

router = Router(name="batch")

_POLL_INTERVAL_SECONDS = 3.0
_MAX_POLL_SECONDS = 30 * 60


# --- Starting a batch -------------------------------------------------------


async def _begin_batch(db_user_id: str, state: FSMContext) -> tuple[str, str]:
    """Creates the Batch row and FSM state. Returns (text, batch_id)."""
    settings = get_settings()
    async with get_session() as session:
        batch_repo = BatchRepository(session)
        batch = await batch_repo.create(db_user_id)

    await state.set_state(BatchFlow.collecting)
    await state.update_data(batch_id=batch.id, count=0)

    text = (
        "📦 <b>Пакетли режим бошланди.</b>\n\n"
        f"Менга {settings.max_batch_size} тагача PDF/расм файлини, бирма-бир юборинг. "
        "Тугагач Якунлаш тугмасини босинг, ёки Бекор қилиш билан тўхтатинг."
    )
    return text, batch.id


@router.message(F.text == "/batch")
async def cmd_batch(message: Message, db_user_id: str, state: FSMContext) -> None:
    text, batch_id = await _begin_batch(db_user_id, state)
    sent = await message.answer(text, reply_markup=batch_collection_keyboard(batch_id, 0))
    await state.update_data(status_message_id=sent.message_id)


@router.callback_query(F.data == MainMenuCallback.BATCH)
async def cb_start_batch(callback: CallbackQuery, db_user_id: str, state: FSMContext) -> None:
    await callback.answer()
    message = editable_message(callback)
    if message is None:
        return
    text, batch_id = await _begin_batch(db_user_id, state)
    sent = await message.answer(text, reply_markup=batch_collection_keyboard(batch_id, 0))
    await state.update_data(status_message_id=sent.message_id)


# --- Collecting files --------------------------------------------------------


@router.message(F.document, BatchFlow.collecting)
async def handle_batch_document(message: Message, db_user_id: str, state: FSMContext) -> None:
    await _collect_upload(message, db_user_id, state, receive_document_upload)


@router.message(F.photo, BatchFlow.collecting)
async def handle_batch_photo(message: Message, db_user_id: str, state: FSMContext) -> None:
    await _collect_upload(message, db_user_id, state, receive_photo_upload)


async def _collect_upload(message: Message, db_user_id: str, state: FSMContext, receive_fn) -> None:
    settings = get_settings()
    data = await state.get_data()
    batch_id: str | None = data.get("batch_id")
    count: int = data.get("count", 0)
    status_message_id: int | None = data.get("status_message_id")

    if batch_id is None:
        return  # stale state without a batch - shouldn't happen, but don't crash

    if count >= settings.max_batch_size:
        await message.reply(
            f"⚠️ Пакет чегарасига етди ({settings.max_batch_size}). "
            "Ҳозиргача қўшилганларни қайта ишлаш учун Якунлаш тугмасини босинг."
        )
        return

    upload = await receive_fn(message)
    if upload is None:
        return

    stored = await store_and_inspect(db_user_id, upload, batch_id=batch_id)
    if stored is None:
        return

    await upload.status_message.edit_text(_short_confirmation(stored))

    count += 1
    await state.update_data(count=count)

    if status_message_id is not None:
        assert message.bot is not None
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=status_message_id,
                text=_collection_status_text(count, settings.max_batch_size),
                reply_markup=batch_collection_keyboard(batch_id, count),
            )
        except Exception:
            pass


def _short_confirmation(stored: StoredDocument) -> str:
    pages = stored.inspection.page_count
    return f"✅ {stored.filename} қўшилди ({pages} бет).{stored.reuse_note}"


def _collection_status_text(count: int, max_count: int) -> str:
    return (
        f"📦 <b>Пакетли режим:</b> {count}/{max_count} файл қўшилди.\n"
        "Яна файл юборинг, қайта ишлаш учун Якунлаш, ёки Бекор қилиш билан тўхтатинг."
    )


# --- Finish / cancel collection ----------------------------------------------


@router.callback_query(F.data.startswith(f"{BatchControlCallback.PREFIX}:"))
async def handle_batch_control(callback: CallbackQuery, db_user_id: str, state: FSMContext) -> None:
    await callback.answer()
    message = editable_message(callback)
    if message is None or not callback.data:
        return

    action, batch_id = BatchControlCallback.parse(callback.data)

    data = await state.get_data()
    if data.get("batch_id") != batch_id:
        await safe_edit_text(message, "Бу пакет энди фаол эмас.")
        return

    if action == "cancel":
        await _cancel_batch(batch_id)
        await state.clear()
        await safe_edit_text(message, "❌ Пакет бекор қилинди. Юкланган файллар ўчирилди.")
        return

    if action != "finish":
        return

    async with get_session() as session:
        doc_repo = DocumentRepository(session)
        documents = await doc_repo.list_for_batch(batch_id)

    if not documents:
        await safe_edit_text(message, "⚠️ Ҳали ҳеч қандай файл қўшилмаган. Аввал файл юборинг, ёки Бекор қилинг.")
        return

    await state.clear()  # the format step is keyed purely off batch_id in the callback data
    text = f"📦 <b>{len(documents)} та ҳужжат тайёр.</b>\n\nБутун пакет учун чиқиш форматини танланг:"
    await safe_edit_text(message, text)
    try:
        await message.edit_reply_markup(reply_markup=batch_format_keyboard(batch_id))
    except Exception:
        pass


async def _cancel_batch(batch_id: str) -> None:
    async with get_session() as session:
        doc_repo = DocumentRepository(session)
        batch_repo = BatchRepository(session)
        documents = await doc_repo.list_for_batch(batch_id)
        for document in documents:
            files.delete_if_exists(f"uploads/{document.stored_filename}")
            await doc_repo.delete(document.id)
        await batch_repo.set_status(batch_id, BatchStatus.CANCELLED)


# --- Format choice → dispatch → aggregate progress → ZIP delivery -----------


@router.callback_query(F.data.startswith(f"{BatchFormatCallback.PREFIX}:"))
async def handle_batch_format(callback: CallbackQuery, db_user_id: str) -> None:
    await callback.answer()
    message = editable_message(callback)
    if message is None or not callback.data:
        return

    action, batch_id = BatchFormatCallback.parse(callback.data)

    async with get_session() as session:
        batch_repo = BatchRepository(session)
        doc_repo = DocumentRepository(session)
        batch = await batch_repo.get(batch_id)
        if batch is None or batch.user_id != db_user_id:
            await safe_edit_text(message, "❌ Пакет топилмади ёки энди мавжуд эмас.")
            return
        documents = await doc_repo.list_for_batch(batch_id)

    if action == "cancel":
        await _cancel_batch(batch_id)
        await safe_edit_text(message, "❌ Пакет бекор қилинди. Юкланган файллар ўчирилди.")
        return

    if not documents:
        await safe_edit_text(message, "⚠️ Бу пакетда файллар йўқ.")
        return

    if action not in EXPECTED_FORMATS:
        return

    db_format = DBOutputFormat(action)
    filenames = {document.id: document.original_filename for document in documents}

    job_ids: list[str] = []
    async with get_session() as session:
        job_repo = ProcessingJobRepository(session)
        batch_repo = BatchRepository(session)
        for document in documents:
            job = await job_repo.create(document.id, db_format)
            job_ids.append(job.id)
        await batch_repo.set_status(batch_id, BatchStatus.PROCESSING, requested_format=db_format)

    from app.worker.tasks import process_document_task

    for document, job_id in zip(documents, job_ids, strict=True):
        # auto_confirm_review=True: batch mode never pauses for interactive
        # OCR review (see app/bot/handlers/review.py docstring) - any
        # uncertain content is instead called out in the final summary.
        process_document_task.delay(document.id, job_id, action, True)

    await safe_edit_text(message, _batch_progress_text(0, len(documents)))

    asyncio.create_task(
        _track_batch(
            message=message,
            batch_id=batch_id,
            action=action,
            document_ids=[document.id for document in documents],
            job_ids=job_ids,
            filenames=filenames,
        )
    )


async def _track_batch(
    message: Message,
    batch_id: str,
    action: str,
    document_ids: list[str],
    job_ids: list[str],
    filenames: dict[str, str],
) -> None:
    total = len(document_ids)
    elapsed = 0.0
    last_text: str | None = None

    try:
        while elapsed < _MAX_POLL_SECONDS:
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
            elapsed += _POLL_INTERVAL_SECONDS

            statuses: dict[str, JobStatus] = {}
            async with get_session() as session:
                job_repo = ProcessingJobRepository(session)
                for document_id, job_id in zip(document_ids, job_ids, strict=True):
                    job = await job_repo.get(job_id)
                    statuses[document_id] = job.status if job is not None else JobStatus.FAILED

            done = sum(1 for s in statuses.values() if s in (JobStatus.SUCCEEDED, JobStatus.FAILED))
            text = _batch_progress_text(done, total, statuses.values())
            if text != last_text:
                await safe_edit_text(message, text)
                last_text = text

            if done == total:
                await _finish_batch(message, batch_id, action, document_ids, filenames, statuses)
                return

        await safe_edit_text(
            message, "⌛ Пакетни қайта ишлаш кутилганидан узоқ давом этмоқда. Бироздан сўнг /history орқали текширинг."
        )
    except Exception:
        logger.exception("Error while tracking batch %s", batch_id)


def _batch_progress_text(done: int, total: int, statuses=None) -> str:
    lines = [f"📦 <b>Пакетли қайта ишлаш:</b> {done}/{total} та ҳужжат тайёр"]
    if statuses:
        icon_map = {JobStatus.SUCCEEDED: "✅", JobStatus.FAILED: "❌"}
        icons = " ".join(icon_map.get(status, "⏳") for status in statuses)
        lines.append(icons)
    return "\n".join(lines)


async def _finish_batch(
    message: Message,
    batch_id: str,
    action: str,
    document_ids: list[str],
    filenames: dict[str, str],
    statuses: dict[str, JobStatus],
) -> None:
    expected = EXPECTED_FORMATS[action]
    zip_entries: list[tuple[str, bytes]] = []
    failed_filenames: list[str] = []
    uncertain_filenames: list[str] = []

    async with get_session() as session:
        doc_repo = DocumentRepository(session)
        gen_repo = GeneratedFileRepository(session)
        for document_id in document_ids:
            if statuses.get(document_id) != JobStatus.SUCCEEDED:
                failed_filenames.append(filenames.get(document_id, document_id))
                continue

            document = await doc_repo.get(document_id)
            if document is not None and document.has_uncertain_content:
                uncertain_filenames.append(filenames.get(document_id, document_id))

            base_name = filenames[document_id].rsplit(".", 1)[0][:80] or "document"
            for fmt in expected:
                existing = await gen_repo.find_existing(document_id, fmt)
                if existing is None:
                    continue
                try:
                    data = files.absolute_path_for(existing.path).read_bytes()
                except Exception:
                    logger.exception(
                        "Failed to read generated file for batch document %s", document_id
                    )
                    continue
                zip_entries.append((f"{base_name}{FILENAME_SUFFIX[fmt]}", data))

    async with get_session() as session:
        batch_repo = BatchRepository(session)
        await batch_repo.set_status(batch_id, BatchStatus.COMPLETED)

    if not zip_entries:
        await safe_edit_text(message, "❌ Пакет қайта ишлаш тугади, лекин натижа файллари яратилмади.")
        return

    succeeded_count = len(document_ids) - len(failed_filenames)
    summary_lines = [
        f"✅ Пакет тайёр: {succeeded_count} та ҳужжатдан {len(zip_entries)} та файл яратилди."
    ]
    if failed_filenames:
        summary_lines.append("⚠️ Хатолик: " + ", ".join(failed_filenames[:10]))
    if uncertain_filenames:
        summary_lines.append(
            "🔍 Ноаниқ/ўқиб бўлмайдиган мазмун бор (текширилмаган - пакетли режим "
            "интерактив кўрикни ўтказиб юборади): " + ", ".join(uncertain_filenames[:10])
        )
    summary = "\n".join(summary_lines)

    archive_bytes = files.build_zip(zip_entries)
    await message.answer_document(
        BufferedInputFile(archive_bytes, filename="batch_results.zip"),
        caption=summary,
    )
    await safe_edit_text(message, summary)
