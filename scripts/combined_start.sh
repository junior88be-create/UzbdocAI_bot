#!/bin/bash
# `wait -n` below requires bash (not POSIX sh/dash) - the python:3.12-slim
# base image (Debian) ships /bin/bash even though /bin/sh is dash.
#
# Combined entrypoint for single-container deployment (e.g. Railway, or any
# platform without a shared filesystem/volume across services).
#
# Why this exists: the bot, Celery worker, and Celery beat are designed as
# three independent processes (see docker-compose.yml) that share
# storage/uploads, storage/processed, and storage/outputs via one Docker
# volume. That works locally, but on a platform where each "service" is its
# own isolated container with its own filesystem (Railway, for example),
# the bot writes an uploaded file the worker can never see, and the worker
# writes a generated file the bot can never read back to send to the user -
# every job fails with FileNotFoundError. Running all three processes in
# one container gives them the one filesystem they actually need to share.
#
# If any process exits (crash or otherwise), this script exits too, so the
# platform's own restart policy brings all three back up together rather
# than leaving the deployment in a half-alive state.
#
# `alembic upgrade head` runs first, before any process starts: without it,
# a schema-changing migration (e.g. new User columns) ships in code but
# never gets applied to the real database, so every query touching the
# affected table starts failing in production the moment the new code
# deploys - this bit us for real once already.
#
# The first time this ran against the real production database, it failed
# outright: that database's schema was originally created by
# init_models()'s Base.metadata.create_all() (see app/database/database.py),
# never by Alembic, so its alembic_version tracking table didn't exist and
# `alembic upgrade head` tried to replay every migration from 0001 onward -
# including CREATE TYPE/CREATE TABLE for things that already existed,
# which failed with "already exists" and crash-looped the whole container
# (all three processes, since this line runs before any of them start). The
# fallback below detects exactly that one-time condition and stamps the
# last migration that predates Alembic ever running here (0004_add_search -
# every column/index it adds was already present in the live schema, since
# create_all() builds from the current model definitions, not a historical
# snapshot) as already applied, then retries - after which normal deploys
# never hit this branch again.
set -eu

echo "[combined_start] running database migrations..."
if ! alembic upgrade head > /tmp/alembic_upgrade.log 2>&1; then
    if grep -qi "already exists" /tmp/alembic_upgrade.log; then
        echo "[combined_start] schema predates Alembic tracking (created via create_all()) - stamping 0004_add_search baseline and retrying..."
        alembic stamp 0004_add_search
        alembic upgrade head
    else
        cat /tmp/alembic_upgrade.log
        exit 1
    fi
fi

echo "[combined_start] starting celery worker..."
celery -A app.worker.celery_app worker --loglevel=INFO --concurrency=2 &
WORKER_PID=$!

echo "[combined_start] starting celery beat..."
celery -A app.worker.celery_app beat --loglevel=INFO &
BEAT_PID=$!

echo "[combined_start] starting bot..."
python -m app.main &
BOT_PID=$!

trap 'kill -TERM $WORKER_PID $BEAT_PID $BOT_PID 2>/dev/null' TERM INT

wait -n "$WORKER_PID" "$BEAT_PID" "$BOT_PID"
EXIT_CODE=$?
echo "[combined_start] a process exited (code $EXIT_CODE) - stopping the rest"
kill -TERM $WORKER_PID $BEAT_PID $BOT_PID 2>/dev/null || true
wait
exit "$EXIT_CODE"
