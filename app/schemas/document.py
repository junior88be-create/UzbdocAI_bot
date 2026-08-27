"""Non-persistence DTOs used to move data between services and bot handlers."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class SourceKind(str, Enum):
    """How the source document must be processed."""

    DIGITAL_PDF = "digital_pdf"
    SCANNED_PDF = "scanned_pdf"
    MIXED_PDF = "mixed_pdf"
    IMAGE = "image"


class OutputFormat(str, Enum):
    DOCX = "docx"
    XLSX = "xlsx"
    MARKDOWN = "md"
    JSON = "json"


class DocumentInspection(BaseModel):
    """Result of the cheap, local (non-Gemini) inspection pass."""

    source_kind: SourceKind
    page_count: int
    digital_text_pages: int
    scanned_pages: int
    extracted_text_by_page: dict[int, str] = {}

    @property
    def needs_vision(self) -> bool:
        return self.source_kind in (SourceKind.SCANNED_PDF, SourceKind.MIXED_PDF, SourceKind.IMAGE)


class ProgressUpdate(BaseModel):
    stage: str
    current_page: int | None = None
    total_pages: int | None = None
    message: str
