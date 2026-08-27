"""Pydantic schema for the structured output returned by Gemini.

This is the contract between gemini_service and everything downstream
(docx/excel/markdown generators). Gemini is instructed (see
app/services/prompts.py) to return JSON matching this shape exactly.

Design note: `text_blocks` is the single authoritative, reading-order
sequence of the document, with content embedded directly in each block
(heading text/level, paragraph text, list items, table headers/rows).
Asking a model to additionally keep separate top-level headings/paragraphs/
tables/lists arrays in sync with that sequence is a real reliability risk
(index drift, duplication, partial mismatches) for LLM-generated JSON - so
those flat arrays are *derived* locally after validation via
`DocumentResult.derive_flat_arrays()` rather than requested from Gemini.
They still exist as top-level fields (per spec) and are what
docx/excel/markdown generators consume directly.

Every extracted value carries confidence/source_page/uncertain so that
downstream consumers (and, optionally, the Telegram UI) can flag anything
Gemini was not sure about instead of silently presenting guessed data.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

TextBlockType = Literal["heading", "paragraph", "list", "table", "signature", "stamp", "other"]


class ExtractedValue(BaseModel):
    """A single recognized value with provenance/confidence metadata."""

    value: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_page: int | None = None
    uncertain: bool = False


class Heading(BaseModel):
    text: str
    level: int = Field(default=1, ge=1, le=6)
    source_page: int | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    uncertain: bool = False


class Paragraph(BaseModel):
    text: str
    source_page: int | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    uncertain: bool = False


class ListItem(BaseModel):
    text: str
    level: int = Field(default=0, ge=0)
    uncertain: bool = False


class ListBlock(BaseModel):
    ordered: bool = False
    items: list[ListItem] = Field(default_factory=list)
    source_page: int | None = None


class TableBlock(BaseModel):
    title: str | None = None
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    source_page: int | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    uncertain: bool = False


class TextBlock(BaseModel):
    """One entry in the document's reading-order sequence.

    Only the fields relevant to `type` are populated:
      heading              -> text, level
      paragraph/signature/
      stamp/other           -> text
      list                  -> ordered, items
      table                 -> table

    `type` is a closed Literal, not a bare str, deliberately: Gemini's
    structured-output mode (response_schema) only hard-enforces an enum
    constraint if one is actually present in the JSON schema derived from
    this model. A bare `str` field let Gemini emit any label it wanted
    (e.g. a "form_field" type for a labeled key/value line in an official
    form-like document) - docx/markdown rendering looked up the renderer
    for that type, found nothing, and silently dropped the block with no
    error, no warning, nothing. That is exactly the failure a real user
    hit: everything after the heading vanished from a form-style document.
    See docx_service.py/markdown_service.py for the belt-and-suspenders
    fallback rendering that also protects against any block whose payload
    doesn't match its declared type (e.g. type="table" with no `table`
    filled in).
    """

    type: TextBlockType
    source_page: int | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    uncertain: bool = False

    text: str | None = None
    level: int | None = Field(default=None, ge=1, le=6)
    ordered: bool | None = None
    items: list[ListItem] = Field(default_factory=list)
    table: TableBlock | None = None


class EntityFields(BaseModel):
    """Domain entities that must never be silently 'corrected' by the model."""

    names: list[ExtractedValue] = Field(default_factory=list)
    dates: list[ExtractedValue] = Field(default_factory=list)
    document_numbers: list[ExtractedValue] = Field(default_factory=list)
    amounts: list[ExtractedValue] = Field(default_factory=list)
    addresses: list[ExtractedValue] = Field(default_factory=list)
    signatures: list[ExtractedValue] = Field(default_factory=list)
    stamps: list[ExtractedValue] = Field(default_factory=list)


class DocumentMetadata(BaseModel):
    title: str | None = None
    detected_document_type: str | None = None
    page_count: int | None = None


class DocumentResult(BaseModel):
    """Root structured-extraction result for one processed document."""

    document_type: str
    language: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    pages: int = Field(default=1, ge=1)

    text_blocks: list[TextBlock] = Field(default_factory=list)

    # Derived from text_blocks after validation - see derive_flat_arrays().
    headings: list[Heading] = Field(default_factory=list)
    paragraphs: list[Paragraph] = Field(default_factory=list)
    tables: list[TableBlock] = Field(default_factory=list)
    lists: list[ListBlock] = Field(default_factory=list)

    entities: EntityFields = Field(default_factory=EntityFields)
    metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _derive_on_load(self) -> DocumentResult:
        # Any time a DocumentResult is constructed (including from Gemini's
        # raw JSON or from a cached file), keep the flat arrays in sync.
        self.derive_flat_arrays()
        return self

    def derive_flat_arrays(self) -> None:
        headings: list[Heading] = []
        paragraphs: list[Paragraph] = []
        tables: list[TableBlock] = []
        lists: list[ListBlock] = []

        for block in self.text_blocks:
            if block.type == "heading" and block.text:
                headings.append(
                    Heading(
                        text=block.text,
                        level=block.level or 1,
                        source_page=block.source_page,
                        confidence=block.confidence,
                        uncertain=block.uncertain,
                    )
                )
            elif block.type in ("paragraph", "signature", "stamp", "other") and block.text:
                paragraphs.append(
                    Paragraph(
                        text=block.text,
                        source_page=block.source_page,
                        confidence=block.confidence,
                        uncertain=block.uncertain,
                    )
                )
            elif block.type == "list" and block.items:
                lists.append(
                    ListBlock(
                        ordered=bool(block.ordered),
                        items=block.items,
                        source_page=block.source_page,
                    )
                )
            elif block.type == "table" and block.table:
                tables.append(block.table)

        self.headings = headings
        self.paragraphs = paragraphs
        self.tables = tables
        self.lists = lists

    def has_uncertain_content(self) -> bool:
        if any(b.uncertain for b in self.text_blocks):
            return True
        for field_list in (
            self.entities.names,
            self.entities.dates,
            self.entities.document_numbers,
            self.entities.amounts,
            self.entities.addresses,
        ):
            if any(v.uncertain for v in field_list):
                return True
        return False

    def to_search_text(self) -> str:
        """Flattens all extracted content into plain text for full-text
        search indexing (see Document.search_text in app/database/models.py).
        Includes uncertain/illegible values too - a rough OCR guess is still
        useful to search on, and the DB column this feeds is separate from
        anything shown as authoritative content to the user.
        """
        parts: list[str] = []

        for block in self.text_blocks:
            if block.text:
                parts.append(block.text)
            for item in block.items:
                parts.append(item.text)
            if block.table is not None:
                if block.table.title:
                    parts.append(block.table.title)
                parts.extend(block.table.headers)
                for row in block.table.rows:
                    parts.extend(row)

        for field_name in (
            "names",
            "dates",
            "document_numbers",
            "amounts",
            "addresses",
            "signatures",
            "stamps",
        ):
            parts.extend(v.value for v in getattr(self.entities, field_name) if v.value)

        if self.metadata.title:
            parts.append(self.metadata.title)

        return " ".join(p for p in parts if p)
