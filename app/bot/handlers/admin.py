"""Admin-only panel: system statistics and user management.

Admins can see aggregate counts and enable/disable users, but never
document content - the repository layer used here never touches file
contents or the structured extraction data.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select

from app.bot.keyboards.admin import admin_menu_keyboard, user_toggle_keyboard
from app.bot.middlewares import log_action
from app.bot.utils import editable_message
from app.database.database import get_session
from app.database.models import Document, DocumentStatus, JobStatus, ProcessingJob, User, UserRole
from app.database.repositories import UserRepository

router = Router(name="admin")


def _require_admin(role: UserRole) -> bool:
    return role == UserRole.ADMIN


@router.message(F.text == "/admin")
async def cmd_admin(message: Message, db_user_role: UserRole) -> None:
    if not _require_admin(db_user_role):
        await message.reply("⛔ Фақат админлар учун.")
        return
    await message.answer("🛠 <b>Админ панели</b>", reply_markup=admin_menu_keyboard())


@router.callback_query(F.data == "admin:stats")
async def cb_admin_stats(callback: CallbackQuery, db_user_role: UserRole) -> None:
    if not _require_admin(db_user_role):
        await callback.answer("Фақат админлар учун.", show_alert=True)
        return

    message = editable_message(callback)
    if message is None:
        await callback.answer()
        return

    async with get_session() as session:
        total_users = (await session.execute(select(func.count()).select_from(User))).scalar_one()
        active_users = (
            await session.execute(select(func.count()).select_from(User).where(User.is_active.is_(True)))
        ).scalar_one()
        total_documents = (await session.execute(select(func.count()).select_from(Document))).scalar_one()
        processed_documents = (
            await session.execute(
                select(func.count()).select_from(Document).where(Document.status == DocumentStatus.PROCESSED)
            )
        ).scalar_one()
        failed_documents = (
            await session.execute(
                select(func.count()).select_from(Document).where(Document.status == DocumentStatus.FAILED)
            )
        ).scalar_one()
        running_jobs = (
            await session.execute(
                select(func.count()).select_from(ProcessingJob).where(ProcessingJob.status == JobStatus.RUNNING)
            )
        ).scalar_one()

    text = (
        "📊 <b>Тизим статистикаси</b>\n\n"
        f"👥 Фойдаланувчилар: {total_users} (фаол: {active_users})\n"
        f"📄 Ҳужжатлар: {total_documents}\n"
        f"✅ Қайта ишланган: {processed_documents}\n"
        f"❌ Хатолик: {failed_documents}\n"
        f"⚙️ Ҳозир ишлаётган вазифалар: {running_jobs}\n"
    )
    await message.answer(text)
    await callback.answer()


@router.callback_query(F.data == "admin:users")
async def cb_admin_users(callback: CallbackQuery, db_user_role: UserRole) -> None:
    if not _require_admin(db_user_role):
        await callback.answer("Фақат админлар учун.", show_alert=True)
        return

    message = editable_message(callback)
    if message is None:
        await callback.answer()
        return

    async with get_session() as session:
        user_repo = UserRepository(session)
        users = await user_repo.list_all()

    if not users:
        await message.answer("Фойдаланувчилар топилмади.")
        await callback.answer()
        return

    for user in users[:30]:
        label = user.username or user.first_name or "(номсиз)"
        text = (
            f"👤 {label} (<code>{user.telegram_id}</code>)\n"
            f"Рол: {user.role.value} | Фаол: {'Ҳа' if user.is_active else 'Йўқ'}"
        )
        await message.answer(text, reply_markup=user_toggle_keyboard(user.id, user.is_active))
    await callback.answer()


@router.callback_query(F.data.startswith("admin:toggle:"))
async def cb_admin_toggle_user(callback: CallbackQuery, db_user_role: UserRole, db_user_id: str) -> None:
    if not _require_admin(db_user_role):
        await callback.answer("Фақат админлар учун.", show_alert=True)
        return

    message = editable_message(callback)
    if message is None or not callback.data:
        await callback.answer()
        return

    target_user_id = callback.data.split(":", 2)[2]

    async with get_session() as session:
        user_repo = UserRepository(session)
        users = await user_repo.list_all()
        target = next((u for u in users if u.id == target_user_id), None)
        if target is None:
            await callback.answer("Фойдаланувчи топилмади.", show_alert=True)
            return
        new_state = not target.is_active
        await user_repo.set_active(target_user_id, new_state)

    await log_action(
        "admin.toggle_user",
        user_id=db_user_id,
        target_user_id=target_user_id,
        new_state=new_state,
    )
    await message.edit_reply_markup(reply_markup=user_toggle_keyboard(target_user_id, new_state))
    await callback.answer("Янгиланди." if new_state else "Фойдаланувчи ўчирилди.")
