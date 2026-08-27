"""Regression coverage for a real production bug: the bot process only ever
does `from app.worker.tasks import process_document_task` - it never
imports app.worker.celery_app directly. @shared_task-decorated tasks bind
to Celery's "current app" proxy, which silently falls back to an
unconfigured default Celery() instance (broker amqp://guest@localhost//)
until a real Celery(broker=...) app has been instantiated in the process.
The worker gets that for free via `celery -A app.worker.celery_app`, but
without tasks.py itself importing celery_app, .delay() calls from the bot
process tried to speak AMQP/RabbitMQ instead of the configured Redis broker
and failed with a connection error - only visible once a human actually
clicked a format button against a live deployment, not from any offline
unit test that mocks Celery away.
"""

from __future__ import annotations

from app.config.settings import get_settings


def test_importing_tasks_module_configures_the_real_broker():
    from app.worker.tasks import process_document_task

    settings = get_settings()
    assert process_document_task.app.conf.broker_url == settings.redis_url


def test_importing_tasks_module_sets_the_current_celery_app():
    from celery import current_app

    import app.worker.tasks  # noqa: F401

    settings = get_settings()
    assert current_app.conf.broker_url == settings.redis_url
