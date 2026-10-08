"""Single entry point the bot uses to start a document-processing job.

TASK_BACKEND=celery (default) hands the job to the Celery worker over Redis,
exactly as before. TASK_BACKEND=inline runs the very same
_process_document_async coroutine inside the bot process instead, so a plain
single-machine install (e.g. Windows without Docker) needs neither Redis nor
Celery.

Inline jobs run on one background thread with their own event loop
(asyncio.run per job - the same pattern a Celery worker process uses), not
on the bot's event loop: PDF page rendering and DOCX generation are
synchronous CPU work that would otherwise freeze Telegram polling. A single
worker thread serializes jobs, which also keeps the per-thread Gemini client
(see gemini_service.get_gemini_service) away from concurrent use.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from app.config.settings import get_settings

logger = logging.getLogger(__name__)

_executor: ThreadPoolExecutor | None = None


def _run_inline_job(document_id: str, job_id: str, action: str, auto_confirm_review: bool) -> None:
    from app.worker.tasks import _process_document_async

    try:
        asyncio.run(_process_document_async(document_id, job_id, action, auto_confirm_review))
    except Exception:
        logger.exception("Inline processing job %s for document %s crashed", job_id, document_id)


def enqueue_process_document(
    document_id: str,
    job_id: str,
    action: str,
    auto_confirm_review: bool = False,
) -> None:
    if get_settings().task_backend == "inline":
        global _executor
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="inline-worker")
        _executor.submit(_run_inline_job, document_id, job_id, action, auto_confirm_review)
        return

    from app.worker.tasks import process_document_task

    process_document_task.delay(document_id, job_id, action, auto_confirm_review)
