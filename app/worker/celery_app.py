"""Celery application/worker configuration.

The worker process never receives BOT_TOKEN usage - it only touches the
database, disk storage, and Gemini. Telegram interaction (progress message
edits, file delivery) happens exclusively in the bot process, which polls
job/document status in Postgres. This keeps the Telegram credential scoped
to a single process.
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config.settings import get_settings

_settings = get_settings()

celery_app = Celery(
    "document_ai_bot",
    broker=_settings.redis_url,
    backend=_settings.redis_url,
    include=["app.worker.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    beat_schedule={
        "cleanup-expired-files-hourly": {
            "task": "cleanup_expired_files",
            "schedule": crontab(minute=0),
        },
    },
)
