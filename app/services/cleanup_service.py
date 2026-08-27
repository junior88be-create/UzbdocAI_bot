"""Retention/cleanup: deletes expired file content from disk.

Runs periodically (Celery beat in production, or an asyncio loop in dev -
see app/main.py and app/worker/tasks.py). Document rows are soft-expired
(kept for audit/history, file content removed) rather than hard-deleted, so
/history still shows what was processed without retaining the confidential
content past its retention window.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.database.database import get_session
from app.database.repositories import DocumentRepository, GeneratedFileRepository
from app.utils import files

logger = logging.getLogger(__name__)


@dataclass
class CleanupReport:
    generated_files_removed: int = 0
    documents_expired: int = 0


async def run_cleanup() -> CleanupReport:
    report = CleanupReport()

    async with get_session() as session:
        generated_repo = GeneratedFileRepository(session)
        document_repo = DocumentRepository(session)

        expired_generated = await generated_repo.list_expired()
        for generated_file in expired_generated:
            files.delete_if_exists(generated_file.path)
            await session.delete(generated_file)
            report.generated_files_removed += 1

        expired_documents = await document_repo.list_expired()
        for document in expired_documents:
            if document.structured_data_path:
                files.delete_if_exists(document.structured_data_path)
            files.delete_if_exists(f"uploads/{document.stored_filename}")
            await document_repo.expire(document.id)
            report.documents_expired += 1

    if report.generated_files_removed or report.documents_expired:
        logger.info(
            "Cleanup removed %d generated file(s) and expired %d document(s).",
            report.generated_files_removed,
            report.documents_expired,
        )
    return report
