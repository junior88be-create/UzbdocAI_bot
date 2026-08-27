"""add batches table and documents.batch_id

Revision ID: 0002_add_batches
Revises: 0001_initial
Create Date: 2026-08-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_add_batches"
down_revision: str | None = "0001_initial"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    batch_status = sa.Enum("COLLECTING", "PROCESSING", "COMPLETED", "CANCELLED", name="batch_status")
    batch_output_format = sa.Enum(
        "docx", "xlsx", "md", "json", "all", "auto", name="batch_output_format"
    )

    op.create_table(
        "batches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", batch_status, nullable=False, server_default="COLLECTING"),
        sa.Column("requested_format", batch_output_format, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.add_column(
        "documents",
        sa.Column(
            "batch_id", sa.String(36), sa.ForeignKey("batches.id", ondelete="SET NULL"), nullable=True
        ),
    )
    op.create_index("ix_documents_batch_id", "documents", ["batch_id"])


def downgrade() -> None:
    op.drop_index("ix_documents_batch_id", table_name="documents")
    op.drop_column("documents", "batch_id")
    op.drop_table("batches")

    sa.Enum(name="batch_output_format").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="batch_status").drop(op.get_bind(), checkfirst=True)
