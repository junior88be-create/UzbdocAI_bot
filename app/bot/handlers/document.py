"""Handles single-document PDF/image uploads outside of batch mode: shows
the per-document format-choice keyboard once the file is stored and
inspected.

Batch mode (multiple files collected together) is handled separately in
app/bot/handlers/batch.py, which is registered before this router so its
state-filtered handlers take priority while a batch is being collected -
see that module's docstring. Both flows share the same validation/storage
pipeline (app/bot/upload_pipeline.py).
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

from app.bot.keyboards.document import document_action_keyboard
from app.bot.upload_pipeline import (
    SOURCE_KIND_LABELS,
    StoredDocument,
    receive_document_upload,
    receive_photo_upload,
    store_and_inspect,
)
from app.utils import files

router = Router(name="document")


@router.message(F.document)
async def handle_document_upload(message: Message, db_user_id: str) -> None:
    upload = await receive_document_upload(message)
    if upload is None:
        return

    stored = await store_and_inspect(db_user_id, upload)
    if stored is None:
        return

    await upload.status_message.edit_text(
        _format_received_text(stored), reply_markup=document_action_keyboard(stored.document_id)
    )


@router.message(F.photo)
async def handle_photo_upload(message: Message, db_user_id: str) -> None:
    upload = await receive_photo_upload(message)
    if upload is None:
        return

    stored = await store_and_inspect(db_user_id, upload)
    if stored is None:
        return

    await upload.status_message.edit_text(
        _format_received_text(stored), reply_markup=document_action_keyboard(stored.document_id)
    )


@router.message(F.document.is_not(None) | F.photo.is_not(None))
async def handle_unsupported_attachment(message: Message) -> None:  # pragma: no cover - fallback
    await message.reply("❌ Қўллаб-қувватланмайдиган илова. Илтимос, PDF, JPG ёки PNG файл юборинг.")


def _format_received_text(stored: StoredDocument) -> str:
    size_label = files.human_readable_size(stored.file_size)
    source_label = SOURCE_KIND_LABELS.get(stored.inspection.source_kind, "Номаълум")
    return (
        "✅ <b>Ҳужжат қабул қилинди.</b>\n\n"
        f"📄 Файл номи: {stored.filename}\n"
        f"🗂 Тури: {stored.mime_type}\n"
        f"💾 Ҳажми: {size_label}\n"
        f"📑 Бетлар: {stored.inspection.page_count}\n"
        f"🔍 Аниқланди: {source_label}\n"
        f"⚙️ Ҳолат: қайта ишлашга тайёр"
        f"{stored.reuse_note}\n\n"
        "Чиқиш форматини танланг:"
    )
