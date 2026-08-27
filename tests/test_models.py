"""Regression coverage for a real production bug: SQLAlchemy's Enum type
binds Python enum members by `.name` unless `values_callable` is given -
silently correct for enums where name == value (e.g.
DocumentStatus.RECEIVED = "RECEIVED"), silently WRONG for any enum where
they differ (e.g. SourceKind.IMAGE = "image", OutputFormat.MARKDOWN =
"md"), which fails at insert time with "invalid input value for enum ..."
against the Postgres enum type (created with the lowercase `.value` labels
in the Alembic migrations).

This was only caught by testing against a real Postgres instance - no
sandbox-only test could have found it, since it depends on SQLAlchemy's
Postgres dialect bind-parameter compilation, not on the ORM/ODM layer
these tests can otherwise exercise offline. Verified here by driving the
column type's bind_processor directly, without a live database connection.
"""

from __future__ import annotations

from sqlalchemy.dialects import postgresql

from app.database.models import (
    Batch,
    BatchStatus,
    Document,
    DocumentStatus,
    GeneratedFile,
    JobStatus,
    OutputFormat,
    ProcessingJob,
    SourceKind,
    User,
    UserRole,
    _enum_type,
)

_DIALECT = postgresql.dialect()


def _bound_value(enum_cls, column_name, member):
    column_type = _enum_type(enum_cls, column_name)
    processor = column_type.bind_processor(_DIALECT)
    return processor(member) if processor else member


def test_source_kind_binds_by_value_not_name():
    # The bug case: name ("IMAGE") != value ("image").
    assert _bound_value(SourceKind, "source_kind", SourceKind.IMAGE) == "image"
    assert _bound_value(SourceKind, "source_kind", SourceKind.DIGITAL_PDF) == "digital_pdf"


def test_output_format_binds_by_value_not_name():
    # The bug case: name ("MARKDOWN") != value ("md").
    assert _bound_value(OutputFormat, "output_format", OutputFormat.MARKDOWN) == "md"
    assert _bound_value(OutputFormat, "output_format", OutputFormat.AUTO) == "auto"


def test_enums_where_name_equals_value_still_bind_correctly():
    # These happened to work even without the fix (name == value) - make
    # sure the fix didn't break them.
    assert _bound_value(DocumentStatus, "document_status", DocumentStatus.RECEIVED) == "RECEIVED"
    assert _bound_value(JobStatus, "job_status", JobStatus.PENDING) == "PENDING"
    assert _bound_value(UserRole, "user_role", UserRole.ADMIN) == "ADMIN"
    assert _bound_value(BatchStatus, "batch_status", BatchStatus.COLLECTING) == "COLLECTING"


def test_every_enum_column_in_every_table_uses_the_safe_helper():
    """Guards against a future column being added with a bare SAEnum(...)
    instead of _enum_type(...), which would silently reintroduce this bug
    only for enums where a member's name differs from its value."""
    from sqlalchemy import Enum as SAEnum

    for model in (User, Document, ProcessingJob, GeneratedFile, Batch):
        for column in model.__table__.columns:
            if isinstance(column.type, SAEnum):
                assert column.type.values_callable is not None, (
                    f"{model.__name__}.{column.name} uses a bare SAEnum without "
                    "values_callable - use _enum_type(...) instead"
                )
