"""Tests for Markdown generation."""

from __future__ import annotations

from app.schemas.extraction import DocumentResult, ListItem, TableBlock, TextBlock
from app.services.markdown_service import generate_markdown


def test_generate_markdown_renders_structure_in_order():
    result = DocumentResult(
        document_type="letter",
        language="en",
        pages=1,
        text_blocks=[
            TextBlock(type="heading", text="Section One", level=2, source_page=1),
            TextBlock(type="paragraph", text="Body text.", source_page=1),
            TextBlock(
                type="list",
                ordered=True,
                items=[ListItem(text="First"), ListItem(text="Second")],
                source_page=1,
            ),
            TextBlock(
                type="table",
                table=TableBlock(headers=["Col A", "Col B"], rows=[["1", "2"]]),
                source_page=1,
            ),
        ],
    )

    markdown = generate_markdown(result, source_filename="letter.pdf")

    heading_index = markdown.index("## Section One")
    paragraph_index = markdown.index("Body text.")
    list_index = markdown.index("1. First")
    table_index = markdown.index("| Col A | Col B |")

    assert heading_index < paragraph_index < list_index < table_index
    assert "letter.pdf" in markdown


def test_generate_markdown_marks_uncertain_content():
    result = DocumentResult(
        document_type="letter",
        language="en",
        pages=1,
        text_blocks=[TextBlock(type="paragraph", text="Hard to read", source_page=1, uncertain=True)],
    )
    markdown = generate_markdown(result, source_filename="scan.pdf")
    assert "[UNCERTAIN]" in markdown


def test_generate_markdown_escapes_pipe_in_table_cells():
    result = DocumentResult(
        document_type="table_doc",
        language="en",
        pages=1,
        text_blocks=[
            TextBlock(
                type="table",
                table=TableBlock(headers=["A"], rows=[["value|with|pipes"]]),
                source_page=1,
            ),
        ],
    )
    markdown = generate_markdown(result, source_filename="doc.pdf")
    assert "value\\|with\\|pipes" in markdown


def test_generate_markdown_falls_back_to_text_for_table_type_with_no_table_payload():
    """Regression: a block declared type="table" but with `table` left
    unset used to be silently dropped entirely - see TextBlock.type
    docstring. It must now render its raw text instead of vanishing."""
    result = DocumentResult(
        document_type="notice",
        language="uz",
        pages=1,
        text_blocks=[TextBlock(type="table", text="Ҳисоб рақами: 6000133137", table=None, source_page=1)],
    )
    markdown = generate_markdown(result, source_filename="notice.pdf")
    assert "Ҳисоб рақами: 6000133137" in markdown


def test_generate_markdown_falls_back_to_text_for_list_type_with_no_items():
    result = DocumentResult(
        document_type="notice",
        language="uz",
        pages=1,
        text_blocks=[TextBlock(type="list", text="Пеня 0,1%.", items=[], source_page=1)],
    )
    markdown = generate_markdown(result, source_filename="notice.pdf")
    assert "Пеня 0,1%." in markdown
