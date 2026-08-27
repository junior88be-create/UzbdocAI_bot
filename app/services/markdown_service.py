"""Markdown generation from a validated DocumentResult.

Walks text_blocks in reading order (see extraction.py docstring). Kept
deliberately minimal - no decorative markdown beyond what's needed to
represent headings/paragraphs/lists/tables faithfully.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.schemas.extraction import DocumentResult, TextBlock

_UNCERTAIN_MARK = " `[UNCERTAIN]`"


def _escape_pipe(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _render_heading(block: TextBlock) -> str:
    level = min(max(block.level or 1, 1), 6)
    text = (block.text or "").strip()
    if block.uncertain:
        text += _UNCERTAIN_MARK
    return f"{'#' * level} {text}"


def _render_paragraph(block: TextBlock) -> str:
    text = (block.text or "").strip()
    if block.uncertain:
        text += _UNCERTAIN_MARK
    if block.type == "signature":
        return f"*Signature: {text}*"
    if block.type == "stamp":
        return f"*Stamp: {text}*"
    return text


def _render_list(block: TextBlock) -> str:
    if not block.items:
        # type="list" but no items were actually filled in - fall back to
        # the block's own text rather than silently dropping it (see
        # TextBlock.type docstring for why this defensive path exists).
        return _render_paragraph(block)
    lines = []
    for index, item in enumerate(block.items, start=1):
        indent = "  " * item.level
        marker = f"{index}." if block.ordered else "-"
        text = item.text
        if item.uncertain:
            text += _UNCERTAIN_MARK
        lines.append(f"{indent}{marker} {text}")
    return "\n".join(lines)


def _render_table(block: TextBlock) -> str:
    table_data = block.table
    if table_data is None:
        # type="table" but no table payload - same defensive fallback.
        return _render_paragraph(block)
    lines = []
    if table_data.title:
        title = table_data.title + (_UNCERTAIN_MARK if table_data.uncertain else "")
        lines.append(f"**{title}**\n")

    headers = table_data.headers or (
        [f"Column {i + 1}" for i in range(len(table_data.rows[0]))] if table_data.rows else []
    )
    if not headers:
        return "\n".join(lines)

    lines.append("| " + " | ".join(_escape_pipe(h) for h in headers) + " |")
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")
    for row in table_data.rows:
        padded = list(row) + [""] * max(0, len(headers) - len(row))
        lines.append("| " + " | ".join(_escape_pipe(c) for c in padded[: len(headers)]) + " |")

    return "\n".join(lines)


_RENDERERS = {
    "heading": _render_heading,
    "paragraph": _render_paragraph,
    "signature": _render_paragraph,
    "stamp": _render_paragraph,
    "other": _render_paragraph,
    "list": _render_list,
    "table": _render_table,
}


def generate_markdown(result: DocumentResult, source_filename: str) -> str:
    parts: list[str] = []

    if result.metadata.title:
        parts.append(f"# {result.metadata.title}")

    for block in result.text_blocks:
        renderer = _RENDERERS.get(block.type)
        if renderer:
            rendered = renderer(block)
            if rendered:
                parts.append(rendered)

    if not result.text_blocks:
        parts.append("_No content could be extracted from this document._")

    parts.append("---")
    parts.append("**Processing information**")
    parts.append(f"- Source file: {source_filename}")
    parts.append(f"- Processed: {datetime.now(UTC).isoformat(timespec='seconds')}")
    parts.append(f"- Detected language: {result.language}")
    parts.append(f"- Detected document type: {result.document_type}")
    parts.append(f"- OCR/extraction confidence: {result.confidence:.2f}")
    if result.warnings:
        parts.append("- Warnings:")
        for warning in result.warnings:
            parts.append(f"  - {warning}")

    return "\n\n".join(parts) + "\n"
