"""Voice/audio message transcription.

Unlike the document pipeline (app/bot/upload_pipeline.py + Celery), this
flow is intentionally simple and self-contained: transcription is a single
async I/O-bound Gemini call with no CPU-bound preprocessing (no PDF
rendering), so there is no need to persist the audio, create a Document
row, or hand off to the Celery worker - the handler downloads the audio,
calls Gemini directly, and replies. Nothing is written to disk, so there is
nothing for the retention/cleanup job to track.
"""

from __future__ import annotations

import html
import logging

from aiogram import F, Router
from aiogram.types import BufferedInputFile, Message

from app.bot.upload_pipeline import TELEGRAM_BOT_API_DOWNLOAD_LIMIT, download_telegram_file
from app.config.settings import get_settings
from app.services.gemini_service import GeminiServiceError, get_gemini_service
from app.utils.security import FileValidationError, validate_file_size

logger = logging.getLogger(__name__)

router = Router(name="voice")

# Telegram always encodes voice notes (message.voice) as OGG/Opus, but the
# uploaded-audio case (message.audio) may arrive without a declared
# mime_type - fall back to a Gemini-supported audio type rather than
# rejecting the file outright.
_DEFAULT_VOICE_MIME_TYPE = "audio/ogg"
_DEFAULT_AUDIO_MIME_TYPE = "audio/mpeg"

# Telegram's message can report 4096 characters, but HTML entity escaping
# (&amp; etc.) and our own header can push an unescaped transcript over that
# limit - stay well clear of it and send a file instead when exceeded.
_MAX_INLINE_TRANSCRIPT_CHARS = 3500


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

    if not transcript:
        await status_message.edit_text(
            "🔇 Товуш аниқланмади ёки унда тушунарли нутқ топилмади."
        )
        return

    escaped = html.escape(transcript)
    if len(escaped) <= _MAX_INLINE_TRANSCRIPT_CHARS:
        await status_message.edit_text(f"📝 <b>Матн:</b>\n\n{escaped}")
        return

    await status_message.edit_text("📝 Матн тайёр (файл сифатида юборилмоқда - узунлиги катта):")
    await message.answer_document(
        BufferedInputFile(transcript.encode("utf-8"), filename="transcript.txt")
    )
