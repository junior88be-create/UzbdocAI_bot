"""Tests for the job dispatcher that lets the bot run without Celery/Redis
(TASK_BACKEND=inline) while the Docker/Railway setup keeps using Celery."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.worker import dispatch


def _settings(backend: str) -> SimpleNamespace:
    return SimpleNamespace(task_backend=backend)


def test_inline_backend_runs_job_on_a_background_thread_not_celery(monkeypatch):
    done = threading.Event()
    seen: dict = {}

    def fake_job(document_id, job_id, action, auto_confirm_review):
        seen["args"] = (document_id, job_id, action, auto_confirm_review)
        seen["thread"] = threading.current_thread()
        done.set()

    celery_task = MagicMock()
    monkeypatch.setattr(dispatch, "get_settings", lambda: _settings("inline"))
    monkeypatch.setattr(dispatch, "_run_inline_job", fake_job)
    monkeypatch.setattr("app.worker.tasks.process_document_task", celery_task)

    dispatch.enqueue_process_document("doc-1", "job-1", "docx", True)

    assert done.wait(timeout=5)
    assert seen["args"] == ("doc-1", "job-1", "docx", True)
    # Must not run on the caller's (bot event loop) thread - PDF rendering is
    # synchronous CPU work that would freeze Telegram polling.
    assert seen["thread"] is not threading.main_thread()
    celery_task.delay.assert_not_called()


def test_celery_backend_hands_job_to_celery(monkeypatch):
    celery_task = MagicMock()
    monkeypatch.setattr(dispatch, "get_settings", lambda: _settings("celery"))
    monkeypatch.setattr("app.worker.tasks.process_document_task", celery_task)

    dispatch.enqueue_process_document("doc-2", "job-2", "xlsx")

    celery_task.delay.assert_called_once_with("doc-2", "job-2", "xlsx", False)


def test_task_backend_defaults_to_celery():
    from app.config.settings import Settings

    assert Settings(_env_file=None).task_backend == "celery"
