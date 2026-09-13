"""Tests for the pure cache-freshness check in the Celery task module
(_looks_under_extracted) - the rest of app/worker/tasks.py is tightly
coupled to a DB session and Celery's runtime, matching this test suite's
existing convention of only unit-testing the DB-free logic extracted out
of such modules (see _quota_decision, _looks_garbled).
"""

from __future__ import annotations

from app.schemas.extraction import DocumentResult, TextBlock
from app.worker.tasks import _looks_under_extracted


def _result(num_blocks: int, pages: int) -> DocumentResult:
    return DocumentResult(
        document_type="court_decision",
        language="uz",
        pages=pages,
        text_blocks=[TextBlock(type="paragraph", text=f"block {i}") for i in range(num_blocks)],
    )


def test_result_with_at_least_one_block_per_page_is_trusted():
    assert _looks_under_extracted(_result(num_blocks=2, pages=2)) is False


def test_result_with_more_blocks_than_pages_is_trusted():
    assert _looks_under_extracted(_result(num_blocks=10, pages=2)) is False


def test_result_with_fewer_blocks_than_pages_is_distrusted():
    # Regression: a real 2-page rotated scan produced exactly one text
    # block (a stamp line) - every other word on both pages was dropped,
    # but the task "succeeded" and cached this result under the file's
    # content hash, where it would otherwise keep being reused forever.
    assert _looks_under_extracted(_result(num_blocks=1, pages=2)) is True


def test_completely_empty_result_is_distrusted():
    assert _looks_under_extracted(_result(num_blocks=0, pages=1)) is True
