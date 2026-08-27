"""/history command and 📚 History menu button.

Re-download buttons reuse the same "doc:<format>:<id>" callback handled by
conversion.py - if the file was already generated and hasn't expired, the
worker skips regeneration (and skips Gemini entirely if the cached
structured result is still available), so this is cheap and fast.

Paginated (PAGE_SIZE per page, oldest-first fallback avoided by always
ordering newest-first) via a trailing "Show more" button rather than
loading everything at once - a heavy uploader's history could otherwise
flood the chat with dozens of messages from a single /history call.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.keyboards.document import history_item_keyboard
from app.bot.keyboards.main import MainMenuCallback
from app.bot.utils import editable_message
from app.database.database import get_session
from app.database.models import DocumentStatus
from app.database.repositories import DocumentRepository

router = Router(name="history")

PAGE_SIZE = 5

_STATUS_ICONS = {
    DocumentStatus.RECEIVED: "🆕",
    DocumentStatus.INSPECTING: "🔍",
    DocumentStatus.PROCESSING: "⚙️",
    DocumentStatus.PROCESSED: "✅",
    DocumentStatus.FAILED: "❌",
    DocumentStatus.EXPIRED: "🗑",
}


def _more_keyboard(next_offset: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="▶️ Кўпроқ кўрсатиш", callback_data=f"history:more:{next_offset}")]]
    )


async def _render_history(message: Message, db_user_id: str, offset: int) -> None:
    async with get_session() as session:
        doc_repo = DocumentRepository(session)
        documents = await doc_repo.list_for_user(db_user_id, limit=PAGE_SIZE, offset=offset)
        total = await doc_repo.count_for_user(db_user_id)

    if not documents:
        if offset == 0:
            await message.answer("📚 Сизда ҳали қайта ишланган ҳужжатлар йўқ.")
        else:
            await message.answer("📚 Бошқа ҳужжат йўқ.")
        return

    if offset == 0:
        await message.answer(f"📚 <b>Ҳужжатларингиз</b> (жами {total} та):")

    for document in documents:
        icon = _STATUS_ICONS.get(document.status, "•")
        created = document.created_at.strftime("%Y-%m-%d %H:%M")
        flags = []
        if document.has_uncertain_content:
            flags.append("🔍 ноаниқ мазмун")
        if document.batch_id:
            flags.append("📦 пакет")
        flags_label = f" | {' | '.join(flags)}" if flags else ""
        text = (
            f"{icon} <b>{document.original_filename}</b>\n"
            f"Юкланган: {created} UTC | Бетлар: {document.page_count or '?'} | "
            f"Ҳолат: {document.status.value}{flags_label}"
        )
        if document.status == DocumentStatus.PROCESSED:
            await message.answer(text, reply_markup=history_item_keyboard(document.id))
        else:
            await message.answer(text)

    next_offset = offset + len(documents)
    if next_offset < total:
        await message.answer(
            f"{next_offset}/{total} кўрсатилди.", reply_markup=_more_keyboard(next_offset)
        )


@router.message(F.text == "/history")
async def cmd_history(message: Message, db_user_id: str) -> None:
    await _render_history(message, db_user_id, offset=0)


@router.callback_query(F.data == MainMenuCallback.HISTORY)
async def cb_history(callback: CallbackQuery, db_user_id: str) -> None:
    message = editable_message(callback)
    if message is not None:
        await _render_history(message, db_user_id, offset=0)
    await callback.answer()


@router.callback_query(F.data.startswith("history:more:"))
async def cb_history_more(callback: CallbackQuery, db_user_id: str) -> None:
    await callback.answer()
    message = editable_message(callback)
    if message is None or not callback.data:
        return
    try:
        offset = int(callback.data.rsplit(":", 1)[1])
    except ValueError:
        return
    await _render_history(message, db_user_id, offset=offset)
