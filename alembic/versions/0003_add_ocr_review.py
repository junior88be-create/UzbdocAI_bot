"""add OCR review step columns

Revision ID: 0003_add_ocr_review
Revises: 0002_add_batches
Create Date: 2026-08-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_add_ocr_review"
down_revision: str | None = "0002_add_batches"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("has_uncertain_content", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "documents",
        sa.Column("review_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "processing_jobs",
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("processing_jobs", "needs_review")
    op.drop_column("documents", "review_confirmed")
    op.drop_column("documents", "has_uncertain_content")
