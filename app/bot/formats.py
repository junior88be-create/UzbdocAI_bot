"""Shared mappings between the Telegram-facing format actions
("docx"/"xlsx"/"md"/"all"/"auto") and the DB OutputFormat enum.

Used by both the single-document flow (conversion.py) and the batch flow
(batch.py) so the two stay in sync.
"""

from __future__ import annotations

from app.database.models import OutputFormat as DBOutputFormat

FORMAT_ACTIONS = ("docx", "xlsx", "md", "all", "auto")

EXPECTED_FORMATS: dict[str, set[DBOutputFormat]] = {
    "docx": {DBOutputFormat.DOCX},
    "xlsx": {DBOutputFormat.XLSX},
    "md": {DBOutputFormat.MARKDOWN},
    "all": {DBOutputFormat.DOCX, DBOutputFormat.XLSX, DBOutputFormat.MARKDOWN},
    "auto": {DBOutputFormat.DOCX, DBOutputFormat.XLSX, DBOutputFormat.MARKDOWN},
}

FILENAME_SUFFIX = {
    DBOutputFormat.DOCX: ".docx",
    DBOutputFormat.XLSX: ".xlsx",
    DBOutputFormat.MARKDOWN: ".md",
}
