"""Per-document action keyboard shown right after a file is received."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


class DocumentActionCallback:
    PREFIX = "doc"

    @staticmethod
    def build(document_id: str, action: str) -> str:
        return f"{DocumentActionCallback.PREFIX}:{action}:{document_id}"

    @staticmethod
    def parse(data: str) -> tuple[str, str]:
        _, action, document_id = data.split(":", 2)
        return action, document_id


def document_action_keyboard(document_id: str) -> InlineKeyboardMarkup:
    build = DocumentActionCallback.build
    rows = [
        [
            InlineKeyboardButton(text="📄 DOCX", callback_data=build(document_id, "docx")),
            InlineKeyboardButton(text="📊 XLSX", callback_data=build(document_id, "xlsx")),
            InlineKeyboardButton(text="📝 MD", callback_data=build(document_id, "md")),
        ],
        [
            InlineKeyboardButton(
                text="📦 Барчаси (DOCX+XLSX+MD)", callback_data=build(document_id, "all")
            ),
        ],
        [
            InlineKeyboardButton(text="🤖 Автоматик", callback_data=build(document_id, "auto")),
            InlineKeyboardButton(text="❌ Бекор қилиш", callback_data=build(document_id, "cancel")),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def history_item_keyboard(document_id: str) -> InlineKeyboardMarkup:
    build = DocumentActionCallback.build
    rows = [
        [
            InlineKeyboardButton(text="📄 DOCX", callback_data=build(document_id, "docx")),
            InlineKeyboardButton(text="📊 XLSX", callback_data=build(document_id, "xlsx")),
            InlineKeyboardButton(text="📝 MD", callback_data=build(document_id, "md")),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)
