"""Async SQLAlchemy engine/session setup."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config.settings import get_settings
from app.database.models import Base

_settings = get_settings()

# NullPool is required here, not optional: this module's `engine` singleton
# is imported by both the bot process (one long-lived event loop for its
# whole lifetime - pooling would be fine there) and the Celery worker
# (app/worker/tasks.py wraps every task in a fresh asyncio.run(), which
# creates AND CLOSES a new event loop per task). asyncpg connections are
# bound to the event loop that created them - with normal pooling, a
# connection checked out during task N's loop gets reused during task N+1's
# (different) loop and raises "Event loop is closed" /
# "attached to a different loop". NullPool opens a fresh low-level
# connection per checkout and discards it on checkin, so no connection ever
# crosses an event-loop boundary. This was only caught by testing a second
# real Celery task run against a live worker process - no offline test
# exercises multiple asyncio.run() cycles against the same engine.
engine = create_async_engine(_settings.database_url, echo=False, pool_pre_ping=True, poolclass=NullPool)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_models() -> None:
    """Create tables if they do not exist yet (used in tests / first boot).

    In production, prefer Alembic migrations (alembic upgrade head).
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
