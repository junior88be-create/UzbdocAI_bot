"""Tests for recognizing an audio file sent as a generic Telegram document
(e.g. a phone recorder app's .amr export, attached via the "file" picker
instead of the audio/music picker), routed to voice transcription instead of
being rejected by the document (PDF/image) upload pipeline.
"""

from __future__ import annotations

from datetime import UTC, datetime

from aiogram.types import Chat, Document, Message

from app.bot.handlers.voice import _audio_mime_type_for_document, _document_looks_like_audio


def _document(file_name: str | None = None, mime_type: str | None = None) -> Document:
    return Document(file_id="abc", file_unique_id="u1", file_name=file_name, mime_type=mime_type)


def _message_with(document: Document) -> Message:
    return Message(message_id=1, date=datetime.now(UTC), chat=Chat(id=1, type="private"), document=document)


def test_amr_recording_by_extension_is_recognized_as_audio():
    # Regression: a phone call-recorder .amr export sent via Telegram's
    # generic file picker was rejected outright by the document pipeline's
    # PDF/JPG/PNG-only extension check, never reaching transcription.
    document = _document(file_name="phone_20240320-005048__998993066028.amr")
    assert _document_looks_like_audio(_message_with(document)) is True
    assert _audio_mime_type_for_document(document) == "audio/amr"


def test_declared_audio_mime_type_is_recognized_even_with_unknown_extension():
    document = _document(file_name="recording.bin", mime_type="audio/x-custom")
    assert _audio_mime_type_for_document(document) == "audio/x-custom"


def test_pdf_document_is_not_treated_as_audio():
    document = _document(file_name="report.pdf", mime_type="application/pdf")
    assert _document_looks_like_audio(_message_with(document)) is False
    assert _audio_mime_type_for_document(document) is None


def test_common_audio_extensions_map_to_gemini_supported_mime_types():
    for extension, expected_mime_type in {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".ogg": "audio/ogg",
    }.items():
        document = _document(file_name=f"recording{extension}")
        assert _audio_mime_type_for_document(document) == expected_mime_type
