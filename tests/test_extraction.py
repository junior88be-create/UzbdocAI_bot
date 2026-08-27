"""Tests for the DocumentResult schema (derivation logic) and Gemini
response validation / retry classification. No real Gemini API calls are
made - the SDK client is never invoked over the network here.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_fixed

from app.schemas.extraction import (
    DocumentResult,
    EntityFields,
    ExtractedValue,
    ListItem,
    TableBlock,
    TextBlock,
)
from app.services.gemini_service import (
    GeminiService,
    GeminiServiceError,
    GeminiTransientError,
    _is_transient,
)


def test_text_block_type_rejects_unrecognized_values():
    """Regression: TextBlock.type used to be a bare str, so Gemini could
    emit any label it wanted for a block (e.g. "form_field" for a labeled
    line in an official form). Renderers looked up that type, found no
    match, and silently dropped the block - a real user hit exactly this
    with a form-style document where everything after the heading vanished.
    type is now a closed Literal so both Pydantic and Gemini's structured
    output (response_schema) reject anything outside the known set.
    """
    with pytest.raises(ValidationError):
        TextBlock(type="form_field", text="Ҳисоб рақами: 6000133137")


def test_derive_flat_arrays_from_text_blocks():
    result = DocumentResult(
        document_type="letter",
        language="en",
        pages=1,
        text_blocks=[
            TextBlock(type="heading", text="Title", level=1, source_page=1),
            TextBlock(type="paragraph", text="Hello world", source_page=1),
            TextBlock(
                type="list",
                ordered=False,
                items=[ListItem(text="item1"), ListItem(text="item2")],
                source_page=1,
            ),
            TextBlock(
                type="table",
                table=TableBlock(headers=["A", "B"], rows=[["1", "2"]]),
                source_page=1,
            ),
        ],
    )

    assert len(result.headings) == 1
    assert result.headings[0].text == "Title"
    assert len(result.paragraphs) == 1
    assert result.paragraphs[0].text == "Hello world"
    assert len(result.lists) == 1
    assert len(result.lists[0].items) == 2
    assert len(result.tables) == 1
    assert result.tables[0].headers == ["A", "B"]
    assert result.tables[0].rows == [["1", "2"]]


def test_derive_flat_arrays_is_recomputed_on_reload():
    """Simulates loading from cached JSON: model_validate_json must re-derive
    the flat arrays, not trust whatever was serialized for them."""
    original = DocumentResult(
        document_type="letter",
        language="en",
        pages=1,
        text_blocks=[TextBlock(type="paragraph", text="Only this survives", source_page=1)],
    )
    reloaded = DocumentResult.model_validate_json(original.model_dump_json())
    assert len(reloaded.paragraphs) == 1
    assert reloaded.paragraphs[0].text == "Only this survives"


def test_has_uncertain_content_true_when_entity_uncertain():
    result = DocumentResult(
        document_type="id_card",
        language="uz",
        pages=1,
        entities=EntityFields(names=[ExtractedValue(value="???", uncertain=True)]),
    )
    assert result.has_uncertain_content() is True


def test_has_uncertain_content_false_by_default():
    result = DocumentResult(document_type="letter", language="en", pages=1)
    assert result.has_uncertain_content() is False


def test_to_search_text_includes_headings_paragraphs_lists_and_tables():
    result = DocumentResult(
        document_type="letter",
        language="en",
        pages=1,
        text_blocks=[
            TextBlock(type="heading", text="Annual Report", level=1, source_page=1),
            TextBlock(type="paragraph", text="Revenue increased significantly.", source_page=1),
            TextBlock(
                type="list",
                ordered=False,
                items=[ListItem(text="First bullet"), ListItem(text="Second bullet")],
                source_page=1,
            ),
            TextBlock(
                type="table",
                table=TableBlock(title="Totals", headers=["Quarter", "Amount"], rows=[["Q1", "1000"]]),
                source_page=2,
            ),
        ],
    )
    search_text = result.to_search_text()

    for expected in ("Annual Report", "Revenue increased", "First bullet", "Second bullet", "Totals", "Quarter", "Q1", "1000"):
        assert expected in search_text


def test_to_search_text_includes_entity_values():
    result = DocumentResult(
        document_type="id_card",
        language="uz",
        pages=1,
        entities=EntityFields(
            names=[ExtractedValue(value="Aziz Karimov")],
            dates=[ExtractedValue(value="12.03.2024")],
        ),
    )
    search_text = result.to_search_text()
    assert "Aziz Karimov" in search_text
    assert "12.03.2024" in search_text


def test_to_search_text_empty_document_returns_empty_string():
    result = DocumentResult(document_type="unknown", language="unknown", pages=1)
    assert result.to_search_text() == ""


def test_gemini_service_validate_accepts_well_formed_json():
    service = GeminiService.__new__(GeminiService)  # skip __init__, no client needed
    payload = DocumentResult(document_type="letter", language="en", pages=1).model_dump_json()
    parsed = service._validate(payload)
    assert parsed.document_type == "letter"


def test_gemini_service_validate_rejects_malformed_json():
    service = GeminiService.__new__(GeminiService)
    with pytest.raises(GeminiServiceError):
        service._validate("{this is not valid json")


class _FakeCandidate:
    def __init__(self, finish_reason):
        self.finish_reason = finish_reason


class _FakeResponse:
    def __init__(self, candidates):
        self.candidates = candidates


def test_check_finish_reason_accepts_stop():
    from google.genai import types

    response = _FakeResponse([_FakeCandidate(types.FinishReason.STOP)])
    GeminiService._check_finish_reason(response)  # must not raise


def test_check_finish_reason_accepts_no_candidates():
    GeminiService._check_finish_reason(_FakeResponse([]))  # must not raise


def test_check_finish_reason_rejects_max_tokens_with_actionable_message():
    """Regression: a real document truncated mid-generation (a dense
    bilingual scanned notice) but response_schema's constrained decoding
    still closed the JSON out validly - text_blocks had only 3 entries
    (the last one an empty heading) with no error and no warning. This is
    the guard that must now catch that class of failure explicitly, via
    finish_reason, instead of silently accepting a truncated-but-parseable
    result as if it were the whole document.
    """
    from google.genai import types

    response = _FakeResponse([_FakeCandidate(types.FinishReason.MAX_TOKENS)])
    with pytest.raises(GeminiServiceError, match="катта"):
        GeminiService._check_finish_reason(response)


def test_check_finish_reason_rejects_other_abnormal_reasons():
    from google.genai import types

    response = _FakeResponse([_FakeCandidate(types.FinishReason.SAFETY)])
    with pytest.raises(GeminiServiceError):
        GeminiService._check_finish_reason(response)


def test_is_transient_classifies_known_transient_error():
    assert _is_transient(GeminiTransientError("timeout")) is True


def test_is_transient_classifies_permanent_error_as_non_retryable():
    assert _is_transient(GeminiServiceError("bad request")) is False


@pytest.mark.asyncio
async def test_retry_logic_recovers_from_transient_failures():
    calls = {"count": 0}

    @retry(reraise=True, stop=stop_after_attempt(3), wait=wait_fixed(0), retry=retry_if_exception(_is_transient))
    async def flaky() -> str:
        calls["count"] += 1
        if calls["count"] < 3:
            raise GeminiTransientError("temporary")
        return "ok"

    assert await flaky() == "ok"
    assert calls["count"] == 3


@pytest.mark.asyncio
async def test_retry_logic_does_not_retry_permanent_failures():
    calls = {"count": 0}

    @retry(reraise=True, stop=stop_after_attempt(3), wait=wait_fixed(0), retry=retry_if_exception(_is_transient))
    async def always_fails() -> str:
        calls["count"] += 1
        raise GeminiServiceError("permanent")

    with pytest.raises(GeminiServiceError):
        await always_fails()
    assert calls["count"] == 1
