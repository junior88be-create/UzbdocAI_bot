"""SQLAlchemy 2.x ORM models.

Design notes:
- Document gets a few fields beyond the spec's minimum (content_hash,
  structured_data_path) specifically to support cost-control requirements:
  reuse of a prior Gemini extraction for the same file content, and reuse of
  a stored structured result across multiple export formats without calling
  Gemini again.
- GeneratedFile.expires_at + Document.expires_at back the retention/cleanup
  policy (FILE_RETENTION_HOURS).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[str]:
    return mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))


def _enum_type(enum_cls: type[enum.Enum], name: str) -> SAEnum:
    """SAEnum bound to a Python str-Enum, always serializing by `.value`.

    Without values_callable, SQLAlchemy's default Enum type binds by
    `.name`, not `.value`. That's silently correct for enums where every
    member's name matches its value (e.g. DocumentStatus.RECEIVED =
    "RECEIVED") - and silently WRONG for any enum where they differ (e.g.
    SourceKind.IMAGE = "image", OutputFormat.MARKDOWN = "md"), which raises
    "invalid input value for enum ..." at insert time against the Postgres
    enum type (created with the lowercase `.value` labels in the Alembic
    migrations). Every enum column in this file must use this helper, not
    a bare SAEnum(...), to avoid re-introducing that bug.
    """
    return SAEnum(enum_cls, name=name, values_callable=lambda cls: [member.value for member in cls])


class UserRole(str, enum.Enum):
    USER = "USER"
    ADMIN = "ADMIN"


class DocumentStatus(str, enum.Enum):
    RECEIVED = "RECEIVED"
    INSPECTING = "INSPECTING"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class SourceKind(str, enum.Enum):
    DIGITAL_PDF = "digital_pdf"
    SCANNED_PDF = "scanned_pdf"
    MIXED_PDF = "mixed_pdf"
    IMAGE = "image"
    UNKNOWN = "unknown"


class JobStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class OutputFormat(str, enum.Enum):
    DOCX = "docx"
    XLSX = "xlsx"
    MARKDOWN = "md"
    JSON = "json"
    ALL = "all"
    AUTO = "auto"


class BatchStatus(str, enum.Enum):
    COLLECTING = "COLLECTING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = _uuid_pk()
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[UserRole] = mapped_column(
        _enum_type(UserRole, "user_role"), default=UserRole.USER, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    documents: Mapped[list[Document]] = relationship(back_populates="user")


class Batch(Base):
    """Groups multiple documents uploaded together for batch processing.

    Documents are linked via Document.batch_id. The batch itself carries the
    single requested_format once the user finishes collecting files and
    picks a format - each document still gets its own ProcessingJob (see
    app/worker/tasks.py), so batch processing reuses the existing
    per-document pipeline unchanged.
    """

    __tablename__ = "batches"

    id: Mapped[str] = _uuid_pk()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[BatchStatus] = mapped_column(
        _enum_type(BatchStatus, "batch_status"), default=BatchStatus.COLLECTING, nullable=False
    )
    requested_format: Mapped[OutputFormat | None] = mapped_column(
        _enum_type(OutputFormat, "batch_output_format"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    documents: Mapped[list[Document]] = relationship(back_populates="batch")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = _uuid_pk()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    batch_id: Mapped[str | None] = mapped_column(
        ForeignKey("batches.id", ondelete="SET NULL"), nullable=True
    )

    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)

    # Random, non-guessable name on disk - the original filename is never trusted.
    stored_filename: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)

    status: Mapped[DocumentStatus] = mapped_column(
        _enum_type(DocumentStatus, "document_status"),
        default=DocumentStatus.RECEIVED,
        nullable=False,
    )
    document_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_kind: Mapped[SourceKind] = mapped_column(
        _enum_type(SourceKind, "source_kind"), default=SourceKind.UNKNOWN, nullable=False
    )
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Path (relative to STORAGE_ROOT) to the cached, validated Gemini
    # DocumentResult JSON so repeated export requests skip the API call.
    structured_data_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # OCR review step (see app/bot/handlers/review.py). has_uncertain_content
    # is set once, at extraction time, from DocumentResult.has_uncertain_content()
    # so the bot/batch summary doesn't need to reload the JSON just to check.
    # review_confirmed is set once the user has been shown the review UI and
    # chosen to proceed (with or without corrections) - output generation is
    # gated on it for single-document processing (batch mode bypasses the
    # gate entirely; see ProcessingJob.needs_review).
    has_uncertain_content: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    review_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Full-text search (see app/bot/handlers/search.py). search_text is a
    # flattened plain-text dump of the extracted content (headings,
    # paragraphs, table cells, entity values - see
    # DocumentResult.to_search_text()), populated alongside
    # structured_data_path. search_vector is a Postgres-generated column
    # derived from it plus the filename, indexed with GIN for fast queries.
    #
    # Uses the 'simple' text-search config (tokenize + lowercase, no
    # stemming) deliberately: content spans Uzbek Latin, Uzbek Cyrillic,
    # Russian, and English (spec section 5) - Postgres ships no Uzbek
    # dictionary, and applying English/Russian stemming to mixed-language
    # text would silently corrupt matches more than it would help them.
    #
    # expire() (see repositories.py) nulls search_text on retention expiry,
    # which cascades into search_vector automatically since it's a
    # generated column - expired document content stops being searchable,
    # consistent with the rest of the retention/privacy design.
    search_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('simple', coalesce(search_text, '') || ' ' || coalesce(original_filename, ''))",
            persisted=True,
        ),
        nullable=True,
    )

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="documents")
    batch: Mapped[Batch | None] = relationship(back_populates="documents")
    jobs: Mapped[list[ProcessingJob]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    generated_files: Mapped[list[GeneratedFile]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_documents_search_vector", "search_vector", postgresql_using="gin"),
    )


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[str] = _uuid_pk()
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[JobStatus] = mapped_column(
        _enum_type(JobStatus, "job_status"), default=JobStatus.PENDING, nullable=False
    )
    requested_format: Mapped[OutputFormat] = mapped_column(
        _enum_type(OutputFormat, "output_format"), nullable=False
    )

    # True when the job stopped after extraction (status=SUCCEEDED) because
    # the result contains uncertain content and the OCR review step hasn't
    # been confirmed yet - no output files were generated. The bot presents
    # the review UI instead of delivering files when it sees this. Always
    # False for batch-dispatched jobs (auto_confirm_review=True bypasses the
    # gate - see app/worker/tasks.py).
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    progress_stage: Mapped[str | None] = mapped_column(String(128), nullable=True)
    progress_current: Mapped[int | None] = mapped_column(Integer, nullable=True)
    progress_total: Mapped[int | None] = mapped_column(Integer, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped[Document] = relationship(back_populates="jobs")


class GeneratedFile(Base):
    __tablename__ = "generated_files"

    id: Mapped[str] = _uuid_pk()
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    format: Mapped[OutputFormat] = mapped_column(_enum_type(OutputFormat, "file_format"), nullable=False)

    # Path relative to STORAGE_ROOT - never exposed to the Telegram user directly.
    path: Mapped[str] = mapped_column(String(512), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    document: Mapped[Document] = relationship(back_populates="generated_files")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = _uuid_pk()
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    document_id: Mapped[str | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    log_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
