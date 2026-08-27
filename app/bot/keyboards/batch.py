"""Keyboards for batch upload collection and batch format choice."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


class BatchControlCallback:
    """Buttons shown while files are being collected into a batch."""

    PREFIX = "batchctl"

    @staticmethod
    def build(batch_id: str, action: str) -> str:
        return f"{BatchControlCallback.PREFIX}:{action}:{batch_id}"

    @staticmethod
    def parse(data: str) -> tuple[str, str]:
        _, action, batch_id = data.split(":", 2)
        return action, batch_id


class BatchFormatCallback:
    """Buttons shown once collection is finished, to pick an output format
    for the whole batch."""

    PREFIX = "batchfmt"

    @staticmethod
    def build(batch_id: str, action: str) -> str:
        return f"{BatchFormatCallback.PREFIX}:{action}:{batch_id}"

    @staticmethod
    def parse(data: str) -> tuple[str, str]:
        _, action, batch_id = data.split(":", 2)
        return action, batch_id


def batch_collection_keyboard(batch_id: str, count: int) -> InlineKeyboardMarkup:
    build = BatchControlCallback.build
    rows = [
        [InlineKeyboardButton(text=f"✅ Якунлаш ({count})", callback_data=build(batch_id, "finish"))],
        [InlineKeyboardButton(text="❌ Тўпламни бекор қилиш", callback_data=build(batch_id, "cancel"))],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def batch_format_keyboard(batch_id: str) -> InlineKeyboardMarkup:
    build = BatchFormatCallback.build
    rows = [
        [
            InlineKeyboardButton(text="📄 DOCX", callback_data=build(batch_id, "docx")),
            InlineKeyboardButton(text="📊 XLSX", callback_data=build(batch_id, "xlsx")),
            InlineKeyboardButton(text="📝 MD", callback_data=build(batch_id, "md")),
        ],
        [InlineKeyboardButton(text="📦 Барчаси (DOCX+XLSX+MD)", callback_data=build(batch_id, "all"))],
        [
            InlineKeyboardButton(text="🤖 Автоматик", callback_data=build(batch_id, "auto")),
            InlineKeyboardButton(text="❌ Бекор қилиш", callback_data=build(batch_id, "cancel")),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)
