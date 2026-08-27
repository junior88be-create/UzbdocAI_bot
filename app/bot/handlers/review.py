"""OCR review step.

When a single-document job's extraction contains uncertain content (see
DocumentResult.has_uncertain_content - illegible handwriting, ambiguous
Uzbek Cyrillic/Latin characters, etc.), the worker stops before generating
any output file (app/worker/tasks.py sets ProcessingJob.needs_review).
conversion.py detects that and calls present_review() here instead of
delivering files.

The user sees every flagged item, can tap one to send a corrected value (or
accept it as recognized), then taps Continue to re-dispatch processing - the
structured result is already cached, so re-dispatching never re-calls
Gemini, only (re)generates the output file(s).

Not used for batch processing: batch.py always dispatches with
auto_confirm_review=True, so ProcessingJob.needs_review is never set for
batch-created jobs - see that module for why (interactive review doesn't
fit a hands-off bulk flow). Batch delivery instead surfaces a one-line
warning when any document had uncertain content.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.review import review_keyboard
from app.bot.states.review import ReviewFlow
from app.bot.utils import editable_message, safe_edit_text
from app.database.database import get_session
from app.database.models import OutputFormat as DBOutputFormat
from app.database.repositories import DocumentRepository, ProcessingJobRepository
from app.services.document_service import get_document_service
from app.services.review_service import (
    ReviewItem,
    apply_correction,
    collect_uncertain_items,
    refresh,
)
from app.utils import files

logger = logging.getLogger(__name__)

router = Router(name="review")

_MAX_DISPLAYED_ITEMS = 15


async def present_review(
    message: Message,
    document_id: str,
    job_id: str,
    action: str,
    filename: str,
    page_count: int,
    state: FSMContext,
) -> None:
    """Entry point called from conversion.py when a job comes back with
    needs_review=True."""
    async with get_session() as session:
        doc_repo = DocumentRepository(session)
        document = await doc_repo.get(document_id)

    if document is None or not document.structured_data_path:
        await safe_edit_text(message, "❌ Кўриб чиқиш учун таҳлил натижасини юклаб бўлмади.")
        return

    result = get_document_service().load_result(document.structured_data_path)
    items = collect_uncertain_items(result)

    if not items:
        # Defensive: has_uncertain_content() said yes but nothing resolved -
        # don't strand the user, just proceed as if they'd confirmed.
        await _dispatch_after_review(message, document_id, action, filename, page_count, state)
        return

    await state.set_state(ReviewFlow.reviewing)
    await state.update_data(
        document_id=document_id,
        job_id=job_id,
        action=action,
        filename=filename,
        page_count=page_count,
        status_message_id=message.message_id,
        status_chat_id=message.chat.id,
    )

    await safe_edit_text(message, _review_text(items))
    try:
        await message.edit_reply_markup(reply_markup=review_keyboard(len(items)))
    except Exception:
        pass


def _review_text(items: list[ReviewItem]) -> str:
    lines = [
        f"🔍 <b>OCR кўриги</b> - {len(items)} та элемент ноаниқ деб белгиланди "
        "(манбада ўқиб бўлмайдиган ёки икки хил тушуниладиган).",
        "",
    ]
    for i, item in enumerate(items[:_MAX_DISPLAYED_ITEMS], start=1):
        page_label = f"б.{item.page}" if item.page else "?"
        preview = item.value.strip() or "(ўқиб бўлмайди)"
        if len(preview) > 60:
            preview = preview[:57] + "..."
        lines.append(f'{i}. [{item.category}, {page_label}] "{preview}" ({item.confidence:.0%})')
    if len(items) > _MAX_DISPLAYED_ITEMS:
        lines.append(f"... яна {len(items) - _MAX_DISPLAYED_ITEMS} та (бу ерда алоҳида таҳрирланмайди).")
    lines.append("")
    lines.append("Тузатиш учун рақамни босинг, аниқлангандек давом этиш учун Давом этиш, ёки Бекор қилинг.")
    return "\n".join(lines)


@router.callback_query(F.data.startswith("review:edit:"), ReviewFlow.reviewing)
async def cb_review_edit(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    message = editable_message(callback)
    if message is None or not callback.data:
        return

    try:
        index = int(callback.data.rsplit(":", 1)[1])
    except ValueError:
        return

    data = await state.get_data()
    document_id = data.get("document_id")
    if document_id is None:
        return

    async with get_session() as session:
        doc_repo = DocumentRepository(session)
        document = await doc_repo.get(document_id)
    if document is None or not document.structured_data_path:
        return

    result = get_document_service().load_result(document.structured_data_path)
    items = collect_uncertain_items(result)
    if index >= len(items):
        return
    item = items[index]

    await state.update_data(edit_ref=item.ref)
    await state.set_state(ReviewFlow.awaiting_correction)

    prompt = (
        f"✏️ <b>{item.category}</b> (бет {item.page or '?'})\n"
        f'Ҳозирги қиймат: "{item.value or "(ўқиб бўлмайди)"}"\n\n'
        "Тузатилган матнни юборинг, ёки аниқлангандек қолдириш учун /skip буйруғини юборинг."
    )
    await message.answer(prompt)


@router.message(ReviewFlow.awaiting_correction, F.text == "/skip")
async def msg_review_skip(message: Message, state: FSMContext) -> None:
    await state.set_state(ReviewFlow.reviewing)
    await message.reply("Аниқлангандек қолдирилди.")
    await _refresh_review_message(message, state)


@router.message(ReviewFlow.awaiting_correction, F.text)
async def msg_review_correction(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    document_id = data.get("document_id")
    ref = data.get("edit_ref")
    text = (message.text or "").strip()

    if document_id is None or ref is None or not text:
        await state.set_state(ReviewFlow.reviewing)
        return

    async with get_session() as session:
        doc_repo = DocumentRepository(session)
        document = await doc_repo.get(document_id)

    if document is None or not document.structured_data_path:
        await message.reply("❌ Бу ҳужжатнинг таҳлил натижаси энди топилмади.")
        await state.set_state(ReviewFlow.reviewing)
        return

    document_service = get_document_service()
    result = document_service.load_result(document.structured_data_path)
    applied = apply_correction(result, ref, text)

    if applied:
        result = refresh(result)
        # Overwriting the same content-hash-keyed path is deliberate: identical
        # file content shares one cached result (see document_service.py cost
        # control), so a correction here also improves any other document
        # that reused this exact upload.
        files.save_json_for_document(document.content_hash, result.model_dump_json())
        await message.reply("✅ Янгиланди.")
    else:
        await message.reply("⚠️ Бу элемент энди топилмади - у аллақачон тузатилган бўлиши мумкин.")

    await state.set_state(ReviewFlow.reviewing)
    await _refresh_review_message(message, state)


async def _refresh_review_message(message: Message, state: FSMContext) -> None:
    """Re-renders the persistent review status message after a correction.

    `message` here is whatever triggered the refresh (the user's correction
    reply, or /skip) - only used to reach `.bot`; the message actually
    edited is the original review status message, addressed by the
    chat_id/message_id stored in FSM state.
    """
    data = await state.get_data()
    document_id = data.get("document_id")
    status_message_id = data.get("status_message_id")
    status_chat_id = data.get("status_chat_id")
    if document_id is None or status_message_id is None or status_chat_id is None:
        return

    async with get_session() as session:
        doc_repo = DocumentRepository(session)
        document = await doc_repo.get(document_id)
    if document is None or not document.structured_data_path:
        return

    result = get_document_service().load_result(document.structured_data_path)
    items = collect_uncertain_items(result)

    assert message.bot is not None
    try:
        await message.bot.edit_message_text(
            chat_id=status_chat_id, message_id=status_message_id, text=_review_text(items)
        )
        await message.bot.edit_message_reply_markup(
            chat_id=status_chat_id,
            message_id=status_message_id,
            reply_markup=review_keyboard(len(items)),
        )
    except Exception:
        pass


@router.callback_query(F.data == "review:continue", ReviewFlow.reviewing)
async def cb_review_continue(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    message = editable_message(callback)
    if message is None:
        return

    data = await state.get_data()
    document_id = data.get("document_id")
    action = data.get("action")
    filename = data.get("filename")
    page_count = data.get("page_count", 0)
    if document_id is None or action is None or filename is None:
        return

    async with get_session() as session:
        doc_repo = DocumentRepository(session)
        await doc_repo.confirm_review(document_id)

    await _dispatch_after_review(message, document_id, action, filename, page_count, state)


async def _dispatch_after_review(
    message: Message,
    document_id: str,
    action: str,
    filename: str,
    page_count: int,
    state: FSMContext,
) -> None:
    await state.clear()

    async with get_session() as session:
        job_repo = ProcessingJobRepository(session)
        job = await job_repo.create(document_id, DBOutputFormat(action))
        new_job_id = job.id

    from app.worker.tasks import process_document_task

    process_document_task.delay(document_id, new_job_id, action)

    await safe_edit_text(message, f"📄 Ҳужжат: {filename}\n\n✅ Кўрик тасдиқланди - натижа яратилмоқда...")

    from app.bot.handlers.conversion import _track_job

    asyncio.create_task(
        _track_job(
            message=message,
            document_id=document_id,
            job_id=new_job_id,
            action=action,
            filename=filename,
            page_count=page_count,
            state=state,
        )
    )


@router.callback_query(F.data == "review:cancel", ReviewFlow.reviewing)
async def cb_review_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    message = editable_message(callback)
    await state.clear()
    if message is not None:
        await safe_edit_text(
            message, "❌ Бекор қилинди. Ҳужжат таҳлил қилинди, лекин натижа файли яратилмади."
        )
