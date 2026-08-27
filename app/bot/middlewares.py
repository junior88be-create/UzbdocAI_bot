"""Access-control middleware.

Enforces the allowlist (ALLOWED_TELEGRAM_IDS) and the DB-backed is_active
flag before any handler runs. Fails closed: an empty allowlist means nobody
can use the bot until it is configured. Also upserts the User row and
attaches it to handler data so downstream handlers never need to query it
again.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.config.settings import get_settings
from app.database.database import get_session
from app.database.models import UserRole
from app.database.repositories import AuditLogRepository, UserRepository

logger = logging.getLogger(__name__)

_UNAUTHORIZED_MESSAGE = (
    "⛔ Сизга ушбу ботдан фойдаланишга рухсат берилмаган. "
    "Кириш ҳуқуқини сўраш учун администратор билан боғланинг."
)
_DISABLED_MESSAGE = "⛔ Сизнинг ботдан фойдаланиш ҳуқуқингиз администратор томонидан ўчирилган."


class AccessControlMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        telegram_user = data.get("event_from_user")
        if telegram_user is None:
            return await handler(event, data)

        settings = get_settings()
        telegram_id = telegram_user.id

        if not settings.is_allowed(telegram_id):
            await self._reject(event, _UNAUTHORIZED_MESSAGE)
            return None

        role = UserRole.ADMIN if settings.is_admin(telegram_id) else UserRole.USER

        async with get_session() as session:
            user_repo = UserRepository(session)
            db_user = await user_repo.get_or_create(
                telegram_id=telegram_id,
                username=telegram_user.username,
                first_name=telegram_user.first_name,
                role=role,
            )
            if db_user.role != role:
                db_user.role = role
                await session.flush()
            is_active = db_user.is_active
            data["db_user_id"] = db_user.id
            data["db_user_role"] = db_user.role

        if not is_active:
            await self._reject(event, _DISABLED_MESSAGE)
            return None

        return await handler(event, data)

    @staticmethod
    async def _reject(event: TelegramObject, message: str) -> None:
        # This middleware is registered per-event-type (dispatcher.message /
        # dispatcher.callback_query), so `event` is always one of these two -
        # never a bare Update.
        try:
            if isinstance(event, CallbackQuery):
                await event.answer(message, show_alert=True)
            elif isinstance(event, Message):
                await event.reply(message)
        except Exception:
            logger.debug("Could not deliver rejection message to unauthorized user")


class AuditLogMiddleware(BaseMiddleware):
    """Lightweight audit trail for security-relevant actions.

    Only records the action name/metadata - never document content.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        return await handler(event, data)


async def log_action(
    action: str, user_id: str | None = None, document_id: str | None = None, **metadata: Any
) -> None:
    async with get_session() as session:
        audit_repo = AuditLogRepository(session)
        await audit_repo.log(action=action, user_id=user_id, document_id=document_id, metadata=metadata or None)
