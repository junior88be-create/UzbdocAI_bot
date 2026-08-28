"""Application entrypoint.

Runs the aiogram bot (long polling in dev, webhook in production when
WEBHOOK_URL is set) alongside a minimal FastAPI health-check server used by
Docker/orchestrator health checks.
"""

from __future__ import annotations

import asyncio
import logging

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from fastapi import FastAPI

from app.bot.handlers import (
    admin,
    batch,
    conversion,
    document,
    history,
    review,
    search,
    start,
    voice,
)
from app.bot.handlers import settings as settings_handlers
from app.bot.middlewares import AccessControlMiddleware
from app.config.logging import setup_logging
from app.config.settings import get_settings
from app.database.database import init_models

logger = logging.getLogger(__name__)

health_app = FastAPI(title="Document AI Bot - Health")


@health_app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@health_app.get("/health/ready")
async def readiness() -> dict:
    return {"status": "ready"}


def build_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()

    access_control = AccessControlMiddleware()
    dispatcher.message.middleware(access_control)
    dispatcher.callback_query.middleware(access_control)

    dispatcher.include_router(start.router)
    # batch is registered before document: its handlers are state-filtered
    # (only active during BatchFlow.collecting) and fall through to
    # document's plain upload handlers otherwise - see batch.py docstring.
    dispatcher.include_router(batch.router)
    dispatcher.include_router(document.router)
    dispatcher.include_router(voice.router)
    # review is state-filtered (ReviewFlow) the same way batch is - it must
    # come before any plain-text/message catch-alls, though in practice its
    # own filters are specific enough that order relative to conversion
    # doesn't matter.
    dispatcher.include_router(review.router)
    dispatcher.include_router(conversion.router)
    dispatcher.include_router(history.router)
    dispatcher.include_router(search.router)
    dispatcher.include_router(settings_handlers.router)
    dispatcher.include_router(admin.router)

    return dispatcher


async def _run_health_server(settings) -> None:
    config = uvicorn.Config(
        health_app,
        host=settings.health_host,
        port=settings.health_port,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    await server.serve()


async def _run_polling(bot: Bot, dispatcher: Dispatcher) -> None:
    await bot.delete_webhook(drop_pending_updates=True)
    await dispatcher.start_polling(bot)


async def _run_webhook(bot: Bot, dispatcher: Dispatcher, settings) -> None:
    await bot.set_webhook(
        url=settings.webhook_url,
        secret_token=settings.webhook_secret or None,
        drop_pending_updates=True,
    )

    app = web.Application()
    SimpleRequestHandler(
        dispatcher=dispatcher,
        bot=bot,
        secret_token=settings.webhook_secret or None,
    ).register(app, path=settings.webhook_path)
    setup_application(app, dispatcher, bot=bot)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, settings.webapp_host, settings.webapp_port)
    await site.start()

    # Keep the webhook server alive.
    await asyncio.Event().wait()


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN is not set. Configure it in your environment/.env file.")
    if not settings.allowed_telegram_ids:
        logger.warning(
            "ALLOWED_TELEGRAM_IDS is empty - the bot is currently unusable by anyone "
            "(fail-closed access control). Set it in your environment/.env file."
        )

    await init_models()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = build_dispatcher()

    bot_task = (
        _run_webhook(bot, dispatcher, settings)
        if settings.webhook_url
        else _run_polling(bot, dispatcher)
    )

    logger.info("Starting Document AI Bot (%s mode)", "webhook" if settings.webhook_url else "polling")

    await asyncio.gather(bot_task, _run_health_server(settings))


if __name__ == "__main__":
    asyncio.run(main())
