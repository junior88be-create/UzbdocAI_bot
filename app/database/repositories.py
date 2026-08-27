"""Repository layer - all direct ORM/query access goes through here.

Keeping queries out of bot handlers/services makes it possible to unit test
business logic with a mocked repository and keeps SQL concerns in one place.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    AuditLog,
    Batch,
    BatchStatus,
    Document,
    DocumentStatus,
    GeneratedFile,
    JobStatus,
    OutputFormat,
    ProcessingJob,
    User,
    UserRole,
)


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        result = await self.session.execute(select(User).where(User.telegram_id == telegram_id))
        return result.scalar_one_or_none()

    async def get_or_create(
        self,
        telegram_id: int,
        username: str | None,
        first_name: str | None,
        role: UserRole = UserRole.USER,
    ) -> User:
        user = await self.get_by_telegram_id(telegram_id)
        if user is not None:
            changed = False
            if user.username != username:
                user.username = username
                changed = True
            if user.first_name != first_name:
                user.first_name = first_name
                changed = True
            if changed:
                await self.session.flush()
            return user

        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            role=role,
        )
        self.session.add(user)
        await self.session.flush()
        return user

    async def list_all(self) -> list[User]:
        result = await self.session.execute(select(User).order_by(User.created_at.desc()))
        return list(result.scalars().all())

    async def set_active(self, user_id: str, is_active: bool) -> None:
        await self.session.execute(update(User).where(User.id == user_id).values(is_active=is_active))

    async def count(self) -> int:
        result = await self.session.execute(select(User))
        return len(result.scalars().all())


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **kwargs) -> Document:
        document = Document(**kwargs)
        self.session.add(document)
        await self.session.flush()
        return document

    async def get(self, document_id: str) -> Document | None:
        result = await self.session.execute(select(Document).where(Document.id == document_id))
        return result.scalar_one_or_none()

    async def find_by_hash_for_user(self, user_id: str, content_hash: str) -> Document | None:
        """Used for cost control: reuse a prior successful extraction for identical content."""
        result = await self.session.execute(
            select(Document)
            .where(
                Document.user_id == user_id,
                Document.content_hash == content_hash,
                Document.status == DocumentStatus.PROCESSED,
                Document.structured_data_path.is_not(None),
            )
            .order_by(Document.created_at.desc())
        )
        return result.scalars().first()

    async def update_status(
        self, document_id: str, status: DocumentStatus, error_message: str | None = None
    ) -> None:
        values: dict = {"status": status}
        if error_message is not None:
            values["error_message"] = error_message
        await self.session.execute(update(Document).where(Document.id == document_id).values(**values))

    async def set_structured_result(
        self,
        document_id: str,
        structured_data_path: str,
        document_type: str,
        language: str,
        page_count: int,
        has_uncertain_content: bool = False,
        search_text: str | None = None,
    ) -> None:
        await self.session.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(
                structured_data_path=structured_data_path,
                document_type=document_type,
                language=language,
                page_count=page_count,
                status=DocumentStatus.PROCESSED,
                has_uncertain_content=has_uncertain_content,
                search_text=search_text,
            )
        )

    async def confirm_review(self, document_id: str) -> None:
        """Marks the OCR review step as done - the user has seen the flagged
        items (and optionally corrected some) and chosen to proceed."""
        await self.session.execute(
            update(Document).where(Document.id == document_id).values(review_confirmed=True)
        )

    async def list_for_user(self, user_id: str, limit: int = 20, offset: int = 0) -> list[Document]:
        result = await self.session.execute(
            select(Document)
            .where(Document.user_id == user_id)
            .order_by(Document.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_for_user(self, user_id: str) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(Document).where(Document.user_id == user_id)
        )
        return result.scalar_one()

    async def search(self, user_id: str, query: str, limit: int = 15) -> list[Document]:
        """Full-text search over this user's documents (filename + extracted
        content). See Document.search_vector for the indexing/config
        rationale. websearch_to_tsquery accepts natural user input (quoted
        phrases, "-word" exclusion, implicit AND between terms).
        """
        tsquery = func.websearch_to_tsquery("simple", query)
        rank = func.ts_rank(Document.search_vector, tsquery)
        result = await self.session.execute(
            select(Document)
            .where(Document.user_id == user_id, Document.search_vector.op("@@")(tsquery))
            .order_by(rank.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_expired(self, now: datetime | None = None) -> list[Document]:
        now = now or datetime.now(UTC)
        result = await self.session.execute(
            select(Document).where(
                Document.expires_at.is_not(None),
                Document.expires_at < now,
                Document.status != DocumentStatus.EXPIRED,
            )
        )
        return list(result.scalars().all())

    async def expire(self, document_id: str) -> None:
        """Soft-expire: keep the audit-trail row, drop references to file
        content on disk (which cleanup_service deletes separately).

        search_text is nulled too - search_vector is a generated column
        derived from it, so this also removes the document's content from
        full-text search results (only the filename remains matchable),
        consistent with the rest of the retention/privacy design.
        """
        await self.session.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(status=DocumentStatus.EXPIRED, structured_data_path=None, search_text=None)
        )

    async def count(self) -> int:
        result = await self.session.execute(select(Document))
        return len(result.scalars().all())

    async def list_for_batch(self, batch_id: str) -> list[Document]:
        result = await self.session.execute(
            select(Document).where(Document.batch_id == batch_id).order_by(Document.created_at)
        )
        return list(result.scalars().all())

    async def delete(self, document_id: str) -> None:
        """Hard-deletes a document row (cascades to jobs/generated_files).

        Used only for documents that never left the batch-collection stage
        (i.e. a cancelled batch) - once processing has started, expired
        documents are soft-expired instead (see expire()).
        """
        document = await self.get(document_id)
        if document is not None:
            await self.session.delete(document)


class ProcessingJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, document_id: str, requested_format: OutputFormat) -> ProcessingJob:
        job = ProcessingJob(
            document_id=document_id,
            requested_format=requested_format,
            status=JobStatus.PENDING,
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def get(self, job_id: str) -> ProcessingJob | None:
        result = await self.session.execute(select(ProcessingJob).where(ProcessingJob.id == job_id))
        return result.scalar_one_or_none()

    async def mark_running(self, job_id: str) -> None:
        await self.session.execute(
            update(ProcessingJob)
            .where(ProcessingJob.id == job_id)
            .values(status=JobStatus.RUNNING, started_at=datetime.now(UTC))
        )

    async def update_progress(
        self, job_id: str, stage: str, current: int | None = None, total: int | None = None
    ) -> None:
        await self.session.execute(
            update(ProcessingJob)
            .where(ProcessingJob.id == job_id)
            .values(progress_stage=stage, progress_current=current, progress_total=total)
        )

    async def mark_succeeded(self, job_id: str) -> None:
        await self.session.execute(
            update(ProcessingJob)
            .where(ProcessingJob.id == job_id)
            .values(status=JobStatus.SUCCEEDED, completed_at=datetime.now(UTC))
        )

    async def mark_needs_review(self, job_id: str) -> None:
        """Extraction succeeded but contains uncertain content that hasn't
        been through the OCR review step yet - no output files exist for
        this job. The bot shows the review UI instead of delivering files."""
        await self.session.execute(
            update(ProcessingJob)
            .where(ProcessingJob.id == job_id)
            .values(status=JobStatus.SUCCEEDED, needs_review=True, completed_at=datetime.now(UTC))
        )

    async def mark_failed(self, job_id: str, error_message: str) -> None:
        await self.session.execute(
            update(ProcessingJob)
            .where(ProcessingJob.id == job_id)
            .values(
                status=JobStatus.FAILED,
                completed_at=datetime.now(UTC),
                error_message=error_message[:2000],
            )
        )


class GeneratedFileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        document_id: str,
        format: OutputFormat,
        path: str,
        file_size: int,
        retention_hours: int,
    ) -> GeneratedFile:
        expires_at = datetime.now(UTC) + timedelta(hours=retention_hours)
        generated = GeneratedFile(
            document_id=document_id,
            format=format,
            path=path,
            file_size=file_size,
            expires_at=expires_at,
        )
        self.session.add(generated)
        await self.session.flush()
        return generated

    async def find_existing(self, document_id: str, format: OutputFormat) -> GeneratedFile | None:
        now = datetime.now(UTC)
        result = await self.session.execute(
            select(GeneratedFile)
            .where(
                GeneratedFile.document_id == document_id,
                GeneratedFile.format == format,
                GeneratedFile.expires_at > now,
            )
            .order_by(GeneratedFile.created_at.desc())
        )
        return result.scalars().first()

    async def list_expired(self, now: datetime | None = None) -> list[GeneratedFile]:
        now = now or datetime.now(UTC)
        result = await self.session.execute(
            select(GeneratedFile).where(
                GeneratedFile.expires_at.is_not(None), GeneratedFile.expires_at < now
            )
        )
        return list(result.scalars().all())


class AuditLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def log(
        self,
        action: str,
        user_id: str | None = None,
        document_id: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        entry = AuditLog(action=action, user_id=user_id, document_id=document_id, log_metadata=metadata)
        self.session.add(entry)
        await self.session.flush()


class BatchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, user_id: str) -> Batch:
        batch = Batch(user_id=user_id, status=BatchStatus.COLLECTING)
        self.session.add(batch)
        await self.session.flush()
        return batch

    async def get(self, batch_id: str) -> Batch | None:
        result = await self.session.execute(select(Batch).where(Batch.id == batch_id))
        return result.scalar_one_or_none()

    async def set_status(
        self,
        batch_id: str,
        status: BatchStatus,
        requested_format: OutputFormat | None = None,
    ) -> None:
        values: dict = {"status": status}
        if requested_format is not None:
            values["requested_format"] = requested_format
        if status == BatchStatus.COMPLETED:
            values["completed_at"] = datetime.now(UTC)
        await self.session.execute(update(Batch).where(Batch.id == batch_id).values(**values))
