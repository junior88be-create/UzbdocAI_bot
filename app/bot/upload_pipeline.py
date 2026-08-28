"""Shared upload pipeline: validate + download a Telegram attachment, then
store it and run the cheap local inspection pass.

Extracted so both the single-document flow (app/bot/handlers/document.py)
and the batch-collection flow (app/bot/handlers/batch.py) go through exactly
the same validation/storage/hash-reuse logic instead of duplicating it.

No Gemini call happens anywhere in this module - that only occurs once the
user picks a format (see conversion.py / batch.py), keeping uploads fast and
side-effect-free until the user actually commits to a conversion.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from aiogram.types import Message

from app.config.settings import get_settings
from app.database.database import get_session
from app.database.models import DocumentStatus
from app.database.models import SourceKind as DBSourceKind
from app.database.repositories import DocumentRepository
from app.schemas.document import DocumentInspection, SourceKind
from app.services.document_service import get_document_service
from app.services.pdf_service import PdfProcessingError
from app.utils import files
from app.utils.hashing import sha256_bytes
from app.utils.security import (
    FileValidationError,
    validate_extension,
    validate_file_size,
    validate_magic_bytes,
    validate_mime_type,
)

logger = logging.getLogger(__name__)

# Telegram Bot API caps file downloads via getFile at 20MB regardless of our
# own configured limit, unless a self-hosted Bot API server is used.
TELEGRAM_BOT_API_DOWNLOAD_LIMIT = 20 * 1024 * 1024

SOURCE_KIND_LABELS = {
    SourceKind.DIGITAL_PDF: "Рақамли PDF (матн қатлами аниқланди)",
    SourceKind.SCANNED_PDF: "Сканланган PDF (расм асосида, OCR талаб қилинади)",
    SourceKind.MIXED_PDF: "Аралаш PDF (баъзи бетлар рақамли, баъзилари сканланган)",
    SourceKind.IMAGE: "Расм (OCR талаб қилинади)",
}


@dataclass
class ValidatedUpload:
    file_bytes: bytes
    filename: str
    mime_type: str
    extension: str
    status_message: Message


@dataclass
class StoredDocument:
    document_id: str
    filename: str
    mime_type: str
    file_size: int
    inspection: DocumentInspection
    reuse_note: str


async def download_telegram_file(message: Message, file_id: str) -> bytes:
    assert message.bot is not None  # always set by the dispatcher for incoming updates
    bot_file = await message.bot.get_file(file_id)
    if not bot_file.file_path:
        raise RuntimeError("Telegram did not return a file path for this file")
    buffer = io.BytesIO()
    await message.bot.download_file(bot_file.file_path, destination=buffer)
    return buffer.getvalue()


async def receive_document_upload(message: Message) -> ValidatedUpload | None:
    """Validates and downloads a Telegram `document` attachment.

    Sends a friendly error reply itself and returns None on any failure -
    callers only need to handle the None case by returning.
    """
    settings = get_settings()
    assert message.document is not None  # guaranteed by the F.document filter
    document = message.document
    filename = document.file_name or "document"

    try:
        extension = validate_extension(filename)
        mime_type = validate_mime_type(document.mime_type)
    except FileValidationError as exc:
        await message.reply(f"❌ {exc}")
        return None

    effective_limit = min(settings.max_file_size_bytes, TELEGRAM_BOT_API_DOWNLOAD_LIMIT)
    try:
        validate_file_size(document.file_size or 0, effective_limit)
    except FileValidationError as exc:
        await message.reply(f"❌ {exc}")
        return None

    status_message = await message.reply("⏳ Ҳужжат юкланмоқда...")

    try:
        file_bytes = await download_telegram_file(message, document.file_id)
    except Exception:
        logger.exception("Telegram file download failed")
        await status_message.edit_text("❌ Файлни юклаб бўлмади. Илтимос, қайта уриниб кўринг.")
        return None

    try:
        validate_magic_bytes(file_bytes[:16], mime_type)
    except FileValidationError as exc:
        await status_message.edit_text(f"❌ {exc}")
        return None

    return ValidatedUpload(
        file_bytes=file_bytes,
        filename=filename,
        mime_type=mime_type,
        extension=extension,
        status_message=status_message,
    )


async def receive_photo_upload(message: Message) -> ValidatedUpload | None:
    """Validates and downloads a Telegram `photo` attachment (JPEG)."""
    settings = get_settings()
    assert message.photo is not None  # guaranteed by the F.photo filter
    photo = message.photo[-1]  # largest available resolution

    effective_limit = min(settings.max_file_size_bytes, TELEGRAM_BOT_API_DOWNLOAD_LIMIT)
    try:
        validate_file_size(photo.file_size or 0, effective_limit)
    except FileValidationError as exc:
        await message.reply(f"❌ {exc}")
        return None

    status_message = await message.reply("⏳ Расм юкланмоқда...")

    try:
        file_bytes = await download_telegram_file(message, photo.file_id)
    except Exception:
        logger.exception("Telegram file download failed")
        await status_message.edit_text("❌ Файлни юклаб бўлмади. Илтимос, қайта уриниб кўринг.")
        return None

    mime_type = "image/jpeg"
    try:
        validate_magic_bytes(file_bytes[:16], mime_type)
    except FileValidationError as exc:
        await status_message.edit_text(f"❌ {exc}")
        return None

    filename = f"photo_{photo.file_unique_id}.jpg"
    return ValidatedUpload(
        file_bytes=file_bytes,
        filename=filename,
        mime_type=mime_type,
        extension=".jpg",
        status_message=status_message,
    )


async def store_and_inspect(
    db_user_id: str,
    upload: ValidatedUpload,
    batch_id: str | None = None,
) -> StoredDocument | None:
    """Stores the validated upload, runs local inspection, creates the
    Document row (reusing a prior structured extraction for identical
    content by this user, if one exists), and reports errors on
    `upload.status_message`. Returns None on any failure.
    """
    settings = get_settings()
    status_message = upload.status_message
    content_hash = sha256_bytes(upload.file_bytes)

    try:
        relative_path, _ = files.save_bytes(upload.file_bytes, subdir="uploads", extension=upload.extension)
    except Exception:
        logger.exception("Failed to store uploaded file")
        await status_message.edit_text("❌ Юкланган файлни сақлаб бўлмади. Илтимос, қайта уриниб кўринг.")
        return None

    stored_filename = relative_path.split("/", 1)[1]

    document_service = get_document_service()
    try:
        inspection = document_service.inspect(upload.file_bytes, upload.mime_type, settings.max_pdf_pages)
    except PdfProcessingError as exc:
        files.delete_if_exists(relative_path)
        await status_message.edit_text(f"❌ {exc}")
        return None
    except Exception:
        logger.exception("Document inspection failed")
        files.delete_if_exists(relative_path)
        await status_message.edit_text(
            "❌ Файлни ўқиб бўлмади. У шикастланган ёки қўллаб-қувватланмайдиган форматда бўлиши мумкин."
        )
        return None

    async with get_session() as session:
        doc_repo = DocumentRepository(session)

        reused = await doc_repo.find_by_hash_for_user(db_user_id, content_hash)

        document = await doc_repo.create(
            user_id=db_user_id,
            batch_id=batch_id,
            original_filename=upload.filename[:512],
            mime_type=upload.mime_type,
            file_size=len(upload.file_bytes),
            stored_filename=stored_filename,
            content_hash=content_hash,
            status=DocumentStatus.RECEIVED,
            source_kind=DBSourceKind(inspection.source_kind.value),
            page_count=inspection.page_count,
            expires_at=datetime.now(UTC) + timedelta(hours=settings.file_retention_hours),
        )

        reuse_note = ""
        if reused is not None and reused.structured_data_path:
            await doc_repo.set_structured_result(
                document.id,
                structured_data_path=reused.structured_data_path,
                document_type=reused.document_type or "unknown",
                language=reused.language or "unknown",
                page_count=reused.page_count or inspection.page_count,
                has_uncertain_content=reused.has_uncertain_content,
                search_text=reused.search_text,
            )
            reuse_note = (
                "\n♻️ Худди шундай мазмун олдин қайта ишланган - мавжуд таҳлил қайта "
                "ишлатилмоқда (қўшимча AI харажатисиз)."
            )

        document_id = document.id

    return StoredDocument(
        document_id=document_id,
        filename=upload.filename,
        mime_type=upload.mime_type,
        file_size=len(upload.file_bytes),
        inspection=inspection,
        reuse_note=reuse_note,
    )
