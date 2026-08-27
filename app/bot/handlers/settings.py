"""⚙️ Settings: read-only account/privacy panel.

Per-user preferences (default output format, language override, etc.) are
a natural follow-up (see README "next recommended milestone") but are not
in the MVP - this view surfaces what's already true about the account and
the operational limits instead of a non-functional stub.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.main import MainMenuCallback
from app.bot.utils import editable_message
from app.config.settings import get_settings
from app.database.database import get_session
from app.database.repositories import UserRepository

router = Router(name="settings")


async def _render_settings(message: Message, telegram_id: int) -> None:
    settings = get_settings()
    async with get_session() as session:
        user_repo = UserRepository(session)
        user = await user_repo.get_by_telegram_id(telegram_id)

    role = user.role.value if user else "USER"
    active = "Ҳа" if (user and user.is_active) else "Йўқ"

    text = (
        "⚙️ <b>Созламалар</b>\n\n"
        f"👤 Telegram ID: <code>{telegram_id}</code>\n"
        f"🔑 Рол: {role}\n"
        f"✅ Фаол: {active}\n\n"
        f"📦 Максимал файл ҳажми: {settings.max_file_size_mb} MB\n"
        f"📑 PDF учун максимал бетлар: {settings.max_pdf_pages}\n"
        f"🗑 Файл сақлаш муддати: {settings.file_retention_hours} соат\n\n"
        "🌐 Қўллаб-қувватланадиган тиллар: Ўзбек (лотин), Ўзбек (кирилл), Рус, Инглиз.\n"
        "Ҳужжатнинг асл тили ҳар доим сақланади - ҳужжатлар ҳеч қачон "
        "автоматик таржима қилинмайди.\n\n"
        "🔒 <b>Махфийлик:</b> юкланган файллар ва яратилган ҳужжатлар юқоридаги "
        "сақлаш муддатидан сўнг автоматик ўчирилади. Ҳужжат мазмуни ҳеч қачон "
        "log файлларга ёзилмайди."
    )
    await message.answer(text)


@router.message(F.text == "/settings")
async def cmd_settings(message: Message) -> None:
    if message.from_user is None:
        return
    await _render_settings(message, message.from_user.id)


@router.callback_query(F.data == MainMenuCallback.SETTINGS)
async def cb_settings(callback: CallbackQuery) -> None:
    message = editable_message(callback)
    if message is not None:
        await _render_settings(message, callback.from_user.id)
    await callback.answer()
