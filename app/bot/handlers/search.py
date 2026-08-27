"""Full-text search over a user's previously processed documents.

Query execution lives in DocumentRepository.search (Postgres tsvector/GIN -
see app/database/models.py::Document for the indexing rationale). This
module owns the Telegram UX: prompting for a query (via /search <text> or
the 🔍 Search menu button, which falls back to an FSM prompt), and
rendering results with the same redownload keyboard used in /history.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.document import history_item_keyboard
from app.bot.keyboards.main import MainMenuCallback
from app.bot.states.search import SearchFlow
from app.bot.utils import editable_message
from app.database.database import get_session
from app.database.repositories import DocumentRepository
from app.services.search_service import build_snippet

logger = logging.getLogger(__name__)

router = Router(name="search")

_MAX_RESULTS = 15
_PROMPT = "🔍 Қидирмоқчи бўлган матнни юборинг - у файл номи ва ҳужжат мазмуни бўйича мослайди."


@router.message(Command("search"))
async def cmd_search(message: Message, db_user_id: str, command: CommandObject, state: FSMContext) -> None:
    query = (command.args or "").strip()
    if not query:
        await state.set_state(SearchFlow.awaiting_query)
        await message.answer(_PROMPT)
        return

    await state.clear()
    await _run_search(message, db_user_id, query)


@router.callback_query(F.data == MainMenuCallback.SEARCH)
async def cb_search_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    message = editable_message(callback)
    if message is None:
        return
    await state.set_state(SearchFlow.awaiting_query)
    await message.answer(_PROMPT)


@router.message(SearchFlow.awaiting_query, F.text)
async def msg_search_query(message: Message, db_user_id: str, state: FSMContext) -> None:
    await state.clear()
    query = (message.text or "").strip()
    if not query:
        await message.reply("Сўров бўш - қидириш учун ҳеч нарса йўқ.")
        return
    await _run_search(message, db_user_id, query)


async def _run_search(message: Message, db_user_id: str, query: str) -> None:
    async with get_session() as session:
        doc_repo = DocumentRepository(session)
        try:
            results = await doc_repo.search(db_user_id, query, limit=_MAX_RESULTS)
        except Exception:
            logger.exception("Search query failed")
            await message.answer(
                "❌ Бу қидирув сўровини қайта ишлаб бўлмади. Соддароқ сўз билан уриниб кўринг."
            )
            return

    if not results:
        await message.answer(f'🔍 "{query}" бўйича ҳужжат топилмади.')
        return

    await message.answer(f'🔍 <b>"{query}" бўйича {len(results)} та натижа:</b>')
    for document in results:
        created = document.created_at.strftime("%Y-%m-%d %H:%M")
        text = (
            f"📄 <b>{document.original_filename}</b>\n"
            f"Юкланган: {created} UTC | Бетлар: {document.page_count or '?'} | "
            f"Ҳолат: {document.status.value}"
        )
        snippet = build_snippet(document.search_text, query)
        if snippet:
            text += f"\n<i>…{snippet}…</i>"

        if document.structured_data_path:
            await message.answer(text, reply_markup=history_item_keyboard(document.id))
        else:
            await message.answer(text)
