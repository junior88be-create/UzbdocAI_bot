"""add full-text search (search_text + generated tsvector + GIN index)

Revision ID: 0004_add_search
Revises: 0003_add_ocr_review
Create Date: 2026-08-23

Uses Postgres's 'simple' text search configuration deliberately (tokenize +
lowercase, no stemming) since document content spans Uzbek Latin, Uzbek
Cyrillic, Russian, and English - Postgres has no Uzbek dictionary, and
English/Russian stemming would corrupt matches on mixed-language text more
than it would help. See app/database/models.py::Document for the full
rationale.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_add_search"
down_revision: str | None = "0003_add_ocr_review"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("search_text", sa.Text(), nullable=True))

    op.execute(
        """
        ALTER TABLE documents
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (
            to_tsvector('simple', coalesce(search_text, '') || ' ' || coalesce(original_filename, ''))
        ) STORED
        """
    )
    op.execute("CREATE INDEX ix_documents_search_vector ON documents USING gin (search_vector)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_documents_search_vector")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS search_vector")
    op.drop_column("documents", "search_text")
