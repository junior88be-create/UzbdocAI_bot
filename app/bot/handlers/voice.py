"""Voice/audio message transcription.

Unlike the document pipeline (app/bot/upload_pipeline.py + Celery), this
flow is intentionally simple and self-contained: transcription is a single
async I/O-bound Gemini call with no CPU-bound preprocessing (no PDF
rendering), so there is no need to persist the audio, create a Document
row, or hand off to the Celery worker - the handler downloads the audio,
calls Gemini directly, renders a DOCX in memory, and replies. Nothing is
written to disk, so there is nothing for the retention/cleanup job to track.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import BufferedInputFile, Document, Message

from app.bot.upload_pipeline import TELEGRAM_BOT_API_DOWNLOAD_LIMIT, download_telegram_file
from app.config.settings import get_settings
from app.services.gemini_service import GeminiServiceError, get_gemini_service
from app.services.transcript_docx_service import generate_transcript_docx
from app.utils.security import FileValidationError, validate_file_size

logger = logging.getLogger(__name__)

router = Router(name="voice")

# Telegram always encodes voice notes (message.voice) as OGG/Opus, but the
# uploaded-audio case (message.audio) may arrive without a declared
# mime_type - fall back to a Gemini-supported audio type rather than
# rejecting the file outright.
_DEFAULT_VOICE_MIME_TYPE = "audio/ogg"
_DEFAULT_AUDIO_MIME_TYPE = "audio/mpeg"

# A phone recording (e.g. a call-recorder app's .amr export) sent via
# Telegram's "file" attach button arrives as a generic `message.document`,
# not `message.audio` - Telegram only auto-classifies as audio when it's
# attached through the dedicated audio/music picker. Recognize these by
# extension/mime so they reach transcription instead of being rejected by
# the document pipeline's PDF/image-only extension check (see document.py).
_AUDIO_EXTENSION_MIME_TYPES = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/ogg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".amr": "audio/amr",
    ".wma": "audio/x-ms-wma",
    ".3gp": "audio/3gpp",
    ".webm": "audio/webm",
}


def _audio_mime_type_for_document(document: Document) -> str | None:
    mime_type = document.mime_type or ""
    if mime_type.startswith("audio/"):
        return mime_type
    filename = (document.file_name or "").lower()
    for extension, mapped_mime_type in _AUDIO_EXTENSION_MIME_TYPES.items():
        if filename.endswith(extension):
            return mapped_mime_type
    return None


def _document_looks_like_audio(message: Message) -> bool:
    document = message.document
    return document is not None and _audio_mime_type_for_document(document) is not None


@router.message(F.document, _document_looks_like_audio)
async def handle_audio_sent_as_document(message: Message) -> None:
    document = message.document
    assert document is not None  # guaranteed by the filter above
    mime_type = _audio_mime_type_for_document(document)
    assert mime_type is not None  # guaranteed by the filter above
    await _transcribe_and_reply(
        message,
        file_id=document.file_id,
        # Telegram's generic Document type carries no duration metadata
        # (unlike Voice/Audio), so the duration cap can't be pre-checked
        # here - the file-size cap below still applies.
        duration=0,
        file_size=document.file_size or 0,
        mime_type=mime_type,
    )


@router.message(F.voice)
async def handle_voice_message(message: Message) -> None:
    voice = message.voice
    assert voice is not None  # guaranteed by the F.voice filter
    await _transcribe_and_reply(
        message,
        file_id=voice.file_id,
        duration=voice.duration,
        file_size=voice.file_size or 0,
        mime_type=voice.mime_type or _DEFAULT_VOICE_MIME_TYPE,
    )


@router.message(F.audio)
async def handle_audio_message(message: Message) -> None:
    audio = message.audio
    assert audio is not None  # guaranteed by the F.audio filter
    await _transcribe_and_reply(
        message,
        file_id=audio.file_id,
        duration=audio.duration,
        file_size=audio.file_size or 0,
        mime_type=audio.mime_type or _DEFAULT_AUDIO_MIME_TYPE,
    )


async def _transcribe_and_reply(
    message: Message,
    *,
    file_id: str,
    duration: int,
    file_size: int,
    mime_type: str,
) -> None:
    settings = get_settings()

    if duration > settings.max_voice_duration_seconds:
        max_minutes = settings.max_voice_duration_seconds // 60
        await message.reply(
            f"❌ Овозли хабар жуда узун. Максимал рухсат этилган узунлик: {max_minutes} дақиқа."
        )
        return

    effective_limit = min(settings.max_file_size_bytes, TELEGRAM_BOT_API_DOWNLOAD_LIMIT)
    try:
        validate_file_size(file_size, effective_limit)
    except FileValidationError as exc:
        await message.reply(f"❌ {exc}")
        return

    status_message = await message.reply("⏳ Овозли хабар матнга айлантирилмоқда...")

    try:
        audio_bytes = await download_telegram_file(message, file_id)
    except Exception:
        logger.exception("Telegram voice/audio download failed")
        await status_message.edit_text("❌ Файлни юклаб бўлмади. Илтимос, қайта уриниб кўринг.")
        return

    try:
        transcript = await get_gemini_service().transcribe_audio(audio_bytes, mime_type)
    except GeminiServiceError as exc:
        # Only GeminiServiceError carries a user-facing (already
        # Uzbek-translated) message - GeminiTransientError is an internal
        # retry-classification signal (see gemini_service.py) that should
        # never reach the user verbatim, so it falls through to the generic
        # except below, same as an unrecognized error would.
        await status_message.edit_text(f"❌ {exc}")
        return
    except Exception:
        logger.exception("Unexpected error transcribing voice/audio message")
        await status_message.edit_text("❌ Овозни матнга айлантиришда кутилмаган хатолик юз берди.")
        return

    # Byte/segment counts only - never the transcript content itself - so a
    # report like "it stopped after the first speaker" can be correlated
    # with how much audio/text was actually involved.
    logger.info(
        "Transcribed voice/audio message: mime=%s audio_bytes=%d duration_s=%d segments=%d",
        mime_type,
        len(audio_bytes),
        duration,
        len(transcript.segments),
    )

    if not transcript.segments:
        await status_message.edit_text("🔇 Товуш аниқланмади ёки унда тушунарли нутқ топилмади.")
        return

    docx_bytes = generate_transcript_docx(transcript)
    await status_message.edit_text("📝 Матн тайёр - файл сифатида юборилмоқда:")
    await message.answer_document(BufferedInputFile(docx_bytes, filename="transcript.docx"))
