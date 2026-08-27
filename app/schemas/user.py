"""DTOs describing Telegram users, decoupled from the SQLAlchemy model."""

from __future__ import annotations

from pydantic import BaseModel


class TelegramUserInfo(BaseModel):
    telegram_id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
