"""Tests for the OCR review step's pure logic: enumerating uncertain
content and applying user corrections back into a DocumentResult.
"""

from __future__ import annotations

from app.schemas.extraction import (
    DocumentResult,
    EntityFields,
    ExtractedValue,
    ListItem,
    TableBlock,
    TextBlock,
)
from app.services.review_service import apply_correction, collect_uncertain_items, refresh


def _result_with_mixed_certainty() -> DocumentResult:
    return DocumentResult(
        document_type="letter",
        language="uz",
        pages=1,
        text_blocks=[
            TextBlock(type="heading", text="Clear heading", level=1, source_page=1, uncertain=False),
            TextBlock(
                type="paragraph", text="o'quvchi ismi noaniq", source_page=1, uncertain=True, confidence=0.4
            ),
            TextBlock(type="paragraph", text="This one is fine.", source_page=1, uncertain=False),
            TextBlock(
                type="list",
                ordered=False,
                items=[
                    ListItem(text="clear item", uncertain=False),
                    ListItem(text="???", uncertain=True),
                ],
                source_page=2,
            ),
            TextBlock(
                type="table",
                table=TableBlock(title="Uncertain table", headers=["A"], rows=[["1"]], uncertain=True),
                source_page=2,
            ),
        ],
        entities=EntityFields(
            names=[
                ExtractedValue(value="Aziz", confidence=0.98, source_page=1, uncertain=False),
                ExtractedValue(value="Ш???ов", confidence=0.3, source_page=1, uncertain=True),
            ],
            dates=[ExtractedValue(value="12.03.2024", confidence=0.5, source_page=1, uncertain=True)],
        ),
    )


def test_collect_uncertain_items_finds_all_flagged_content():
    result = _result_with_mixed_certainty()
    items = collect_uncertain_items(result)

    refs = {item.ref for item in items}
    assert "text_blocks:1" in refs  # uncertain paragraph
    assert "text_blocks:3.items:1" in refs  # uncertain list item
    assert "text_blocks:4.table" in refs  # uncertain table
    assert "entities.names:1" in refs
    assert "entities.dates:0" in refs

    # Certain content must not appear.
    assert "text_blocks:0" not in refs  # clear heading
    assert "text_blocks:2" not in refs  # fine paragraph
    assert "entities.names:0" not in refs  # confident name

    assert len(items) == 5


def test_apply_correction_updates_entity_value_and_clears_uncertain():
    result = _result_with_mixed_certainty()
    applied = apply_correction(result, "entities.names:1", "Shokirov")

    assert applied is True
    assert result.entities.names[1].value == "Shokirov"
    assert result.entities.names[1].uncertain is False
    assert result.entities.names[1].confidence == 1.0


def test_apply_correction_updates_paragraph_text_block():
    result = _result_with_mixed_certainty()
    applied = apply_correction(result, "text_blocks:1", "o'quvchi ismi Aziz")

    assert applied is True
    assert result.text_blocks[1].text == "o'quvchi ismi Aziz"
    assert result.text_blocks[1].uncertain is False


def test_apply_correction_updates_list_item():
    result = _result_with_mixed_certainty()
    applied = apply_correction(result, "text_blocks:3.items:1", "second item")

    assert applied is True
    assert result.text_blocks[3].items[1].text == "second item"
    assert result.text_blocks[3].items[1].uncertain is False


def test_apply_correction_clears_table_uncertainty_flag():
    result = _result_with_mixed_certainty()
    applied = apply_correction(result, "text_blocks:4.table", "ignored for tables")

    assert applied is True
    assert result.text_blocks[4].table.uncertain is False


def test_apply_correction_returns_false_for_unknown_ref():
    result = _result_with_mixed_certainty()
    assert apply_correction(result, "entities.names:99", "x") is False
    assert apply_correction(result, "text_blocks:99", "x") is False
    assert apply_correction(result, "not-a-real-ref", "x") is False


def test_correcting_everything_leaves_no_uncertain_items():
    result = _result_with_mixed_certainty()
    for item in collect_uncertain_items(result):
        assert apply_correction(result, item.ref, "fixed") is True

    result = refresh(result)
    assert collect_uncertain_items(result) == []
    assert result.has_uncertain_content() is False


def test_refresh_recomputes_derived_arrays_after_mutation():
    result = _result_with_mixed_certainty()
    apply_correction(result, "text_blocks:1", "now certain")
    refreshed = refresh(result)

    matching = [p for p in refreshed.paragraphs if p.text == "now certain"]
    assert len(matching) == 1
    assert matching[0].uncertain is False
