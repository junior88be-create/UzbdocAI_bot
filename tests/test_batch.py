"""Tests for the pure-logic pieces of batch processing: callback data
round-tripping and progress/status text rendering. The full collection ->
dispatch -> ZIP-delivery flow requires a live Postgres + Telegram session
and is not exercised here (see README "Known limitations").
"""

from __future__ import annotations

from app.bot.handlers.batch import (
    _batch_progress_text,
    _collection_status_text,
    _short_confirmation,
)
from app.bot.keyboards.batch import BatchControlCallback, BatchFormatCallback
from app.bot.upload_pipeline import StoredDocument
from app.database.models import JobStatus
from app.schemas.document import DocumentInspection, SourceKind


def test_batch_control_callback_round_trips():
    data = BatchControlCallback.build("batch-123", "finish")
    action, batch_id = BatchControlCallback.parse(data)
    assert action == "finish"
    assert batch_id == "batch-123"


def test_batch_format_callback_round_trips():
    data = BatchFormatCallback.build("batch-abc", "docx")
    action, batch_id = BatchFormatCallback.parse(data)
    assert action == "docx"
    assert batch_id == "batch-abc"


def test_collection_status_text_shows_count_and_max():
    text = _collection_status_text(3, 10)
    assert "3/10" in text


def test_short_confirmation_shows_page_count_for_one_and_many_pages():
    inspection_one_page = DocumentInspection(
        source_kind=SourceKind.DIGITAL_PDF, page_count=1, digital_text_pages=1, scanned_pages=0
    )
    stored_one = StoredDocument(
        document_id="d1",
        filename="a.pdf",
        mime_type="application/pdf",
        file_size=100,
        inspection=inspection_one_page,
        reuse_note="",
    )
    assert "1 бет)" in _short_confirmation(stored_one)

    inspection_multi = DocumentInspection(
        source_kind=SourceKind.DIGITAL_PDF, page_count=5, digital_text_pages=5, scanned_pages=0
    )
    stored_multi = StoredDocument(
        document_id="d2",
        filename="b.pdf",
        mime_type="application/pdf",
        file_size=100,
        inspection=inspection_multi,
        reuse_note="",
    )
    assert "5 бет)" in _short_confirmation(stored_multi)


def test_short_confirmation_includes_reuse_note():
    inspection = DocumentInspection(
        source_kind=SourceKind.DIGITAL_PDF, page_count=2, digital_text_pages=2, scanned_pages=0
    )
    stored = StoredDocument(
        document_id="d3",
        filename="c.pdf",
        mime_type="application/pdf",
        file_size=100,
        inspection=inspection,
        reuse_note="\n♻️ reused",
    )
    assert "♻️ reused" in _short_confirmation(stored)


def test_batch_progress_text_without_statuses():
    text = _batch_progress_text(2, 5)
    assert "2/5" in text


def test_batch_progress_text_renders_status_icons_in_order():
    statuses = [JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.RUNNING, JobStatus.PENDING]
    text = _batch_progress_text(2, 4, statuses)
    lines = text.splitlines()
    assert "✅ ❌ ⏳ ⏳" in lines[-1]
