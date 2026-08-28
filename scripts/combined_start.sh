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
set -eu

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
