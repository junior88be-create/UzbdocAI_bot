"""Small shared helpers for bot handlers."""

from __future__ import annotations

from aiogram.types import CallbackQuery, Message


def editable_message(callback: CallbackQuery) -> Message | None:
    """Returns callback.message only if it is a real, still-editable Message.

    aiogram types CallbackQuery.message as Message | InaccessibleMessage |
    None because Telegram allows callbacks on messages that were deleted or
    are too old (>48h) to be fetched/edited. Handlers must not blindly call
    .edit_text()/.answer() on it.
    """
    message = callback.message
    if isinstance(message, Message):
        return message
    return None


async def safe_edit_text(message: Message, text: str) -> None:
    """Edits a message, swallowing "message not modified" / deleted / race
    errors - these are expected and not worth surfacing or retrying."""
    try:
        await message.edit_text(text)
    except Exception:
        pass
