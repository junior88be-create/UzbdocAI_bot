"""Regression coverage for a real production bug: the shared async engine
must use NullPool.

app/database/database.py's `engine` singleton is imported by both the bot
process (one long-lived event loop for its whole process lifetime - normal
pooling would be fine there) and the Celery worker (app/worker/tasks.py
wraps every task in a fresh asyncio.run(), creating AND CLOSING a new event
loop per task). asyncpg connections are bound to the event loop that
created them - with a normal pool, a connection checked out during task N's
loop gets reused during task N+1's (different) loop and raises "Event loop
is closed" / "... attached to a different loop", crashing every task after
the first one in a given worker process's lifetime.

This was only ever visible by running a second real Celery task against a
live worker process talking to a live Postgres - no offline unit test
exercises multiple asyncio.run() cycles against the same engine, so this
guards the fix (NullPool) at the configuration level instead: any future
edit that swaps in a normal pool would break this test immediately, without
needing a live database to catch it.
"""

from __future__ import annotations

from sqlalchemy.pool import NullPool

from app.database.database import engine


def test_engine_uses_nullpool_to_avoid_cross_event_loop_connection_reuse():
    assert isinstance(engine.pool, NullPool)
