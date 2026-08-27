"""Admin panel inline keyboard."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


class AdminCallback:
    STATS = "admin:stats"
    USERS = "admin:users"
    TOGGLE_USER = "admin:toggle"


def admin_menu_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="📊 Статистика", callback_data=AdminCallback.STATS),
            InlineKeyboardButton(text="👥 Фойдаланувчилар", callback_data=AdminCallback.USERS),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def user_toggle_keyboard(user_id: str, is_active: bool) -> InlineKeyboardMarkup:
    label = "🔴 Ўчириш" if is_active else "🟢 Ёқиш"
    rows = [[InlineKeyboardButton(text=label, callback_data=f"{AdminCallback.TOGGLE_USER}:{user_id}")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)
