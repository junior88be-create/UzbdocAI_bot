"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    user_role = sa.Enum("USER", "ADMIN", name="user_role")
    document_status = sa.Enum(
        "RECEIVED", "INSPECTING", "PROCESSING", "PROCESSED", "FAILED", "EXPIRED", name="document_status"
    )
    source_kind = sa.Enum(
        "digital_pdf", "scanned_pdf", "mixed_pdf", "image", "unknown", name="source_kind"
    )
    job_status = sa.Enum("PENDING", "RUNNING", "SUCCEEDED", "FAILED", name="job_status")
    output_format = sa.Enum("docx", "xlsx", "md", "json", "all", "auto", name="output_format")
    file_format = sa.Enum("docx", "xlsx", "md", "json", "all", "auto", name="file_format")

    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(255), nullable=True),
        sa.Column("first_name", sa.String(255), nullable=True),
        sa.Column("role", user_role, nullable=False, server_default="USER"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"], unique=True)

    op.create_table(
        "documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("original_filename", sa.String(512), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("stored_filename", sa.String(128), nullable=False, unique=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", document_status, nullable=False, server_default="RECEIVED"),
        sa.Column("document_type", sa.String(64), nullable=True),
        sa.Column("source_kind", source_kind, nullable=False, server_default="unknown"),
        sa.Column("language", sa.String(32), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("structured_data_path", sa.String(512), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_documents_content_hash", "documents", ["content_hash"])

    op.create_table(
        "processing_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "document_id", sa.String(36), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("status", job_status, nullable=False, server_default="PENDING"),
        sa.Column("requested_format", output_format, nullable=False),
        sa.Column("progress_stage", sa.String(128), nullable=True),
        sa.Column("progress_current", sa.Integer(), nullable=True),
        sa.Column("progress_total", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "generated_files",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "document_id", sa.String(36), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("format", file_format, nullable=False),
        sa.Column("path", sa.String(512), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column(
            "document_id",
            sa.String(36),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("log_metadata", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("generated_files")
    op.drop_table("processing_jobs")
    op.drop_table("documents")
    op.drop_table("users")

    sa.Enum(name="file_format").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="output_format").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="job_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="source_kind").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="document_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="user_role").drop(op.get_bind(), checkfirst=True)
