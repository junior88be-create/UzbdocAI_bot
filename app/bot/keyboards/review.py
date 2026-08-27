"""Keyboard for the OCR review step.

Callback data intentionally carries only the item index ("review:edit:3"),
not the document/job/action - those live in FSM state for the duration of
one review session (see app/bot/handlers/review.py), keeping callback_data
well under Telegram's 64-byte limit regardless of id lengths.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

MAX_REVIEW_BUTTONS = 15
_BUTTONS_PER_ROW = 5


def review_keyboard(item_count: int) -> InlineKeyboardMarkup:
    visible = min(item_count, MAX_REVIEW_BUTTONS)
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for i in range(visible):
        row.append(InlineKeyboardButton(text=str(i + 1), callback_data=f"review:edit:{i}"))
        if len(row) == _BUTTONS_PER_ROW:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append(
        [
            InlineKeyboardButton(text="✅ Давом этиш", callback_data="review:continue"),
            InlineKeyboardButton(text="❌ Бекор қилиш", callback_data="review:cancel"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
