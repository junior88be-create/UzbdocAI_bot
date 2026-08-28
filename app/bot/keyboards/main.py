"""Main menu inline keyboard (see spec section 6)."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


class MainMenuCallback:
    UPLOAD_DOCUMENT = "menu:upload_document"
    UPLOAD_IMAGE = "menu:upload_image"
    UPLOAD_VOICE = "menu:upload_voice"
    CREATE_DOCX = "menu:create_docx"
    CREATE_XLSX = "menu:create_xlsx"
    CREATE_MD = "menu:create_md"
    AUTO_FORMAT = "menu:auto_format"
    BATCH = "menu:batch"
    HISTORY = "menu:history"
    SEARCH = "menu:search"
    SETTINGS = "menu:settings"
    HELP = "menu:help"
    ABOUT = "menu:about"


def main_menu_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="📤 Ҳужжат юклаш", callback_data=MainMenuCallback.UPLOAD_DOCUMENT),
            InlineKeyboardButton(text="📷 Расм юклаш", callback_data=MainMenuCallback.UPLOAD_IMAGE),
        ],
        [
            InlineKeyboardButton(text="📄 DOCX яратиш", callback_data=MainMenuCallback.CREATE_DOCX),
            InlineKeyboardButton(text="📊 Excel яратиш", callback_data=MainMenuCallback.CREATE_XLSX),
        ],
        [
            InlineKeyboardButton(text="📝 Markdown яратиш", callback_data=MainMenuCallback.CREATE_MD),
            InlineKeyboardButton(text="🔄 Авто формат", callback_data=MainMenuCallback.AUTO_FORMAT),
        ],
        [
            InlineKeyboardButton(text="🎙 Овоз/аудиони матнга ўгириш", callback_data=MainMenuCallback.UPLOAD_VOICE),
        ],
        [
            InlineKeyboardButton(text="📦 Пакетли қайта ишлаш", callback_data=MainMenuCallback.BATCH),
        ],
        [
            InlineKeyboardButton(text="📚 Тарих", callback_data=MainMenuCallback.HISTORY),
            InlineKeyboardButton(text="🔍 Қидирув", callback_data=MainMenuCallback.SEARCH),
        ],
        [
            InlineKeyboardButton(text="⚙️ Созламалар", callback_data=MainMenuCallback.SETTINGS),
        ],
        [
            InlineKeyboardButton(text="❓ Ёрдам", callback_data=MainMenuCallback.HELP),
            InlineKeyboardButton(text="ℹ️ Бот ҳақида", callback_data=MainMenuCallback.ABOUT),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)
