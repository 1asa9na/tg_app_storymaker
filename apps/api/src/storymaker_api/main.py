import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import async_sessionmaker

from storymaker_api.assets import Storage
from storymaker_api.bot import create_bot, create_dispatcher, register_webhook
from storymaker_api.catalog import Catalog
from storymaker_api.config import get_settings
from storymaker_api.db import create_engine
from storymaker_api.routes import health, me, preview, studio, titles, webhook

logger = logging.getLogger(__name__)

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.app_env,
            send_default_pii=False,
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings.database_url)
        app.state.sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
        app.state.catalog = Catalog()
        app.state.storage = Storage(settings)
        bot = create_bot(settings)
        dispatcher = create_dispatcher(settings, app.state.sessionmaker)
        app.state.bot = bot
        app.state.dispatcher = dispatcher

        if settings.webhook_url and settings.bot_webhook_secret:
            try:
                await register_webhook(bot, dispatcher, settings)
            except Exception:
                # API должен подняться, даже если Telegram недоступен: смотрим doctor.
                logger.exception("failed to register webhook")
        else:
            logger.warning("PUBLIC_URL or BOT_WEBHOOK_SECRET is not set, webhook is not registered")

        yield

        await bot.session.close()
        await engine.dispose()

    is_production = settings.app_env == "production"
    app = FastAPI(
        title="StoryMaker API",
        lifespan=lifespan,
        openapi_url=None if is_production else "/api/openapi.json",
        docs_url=None if is_production else "/api/docs",
        redoc_url=None,
    )
    app.include_router(health.router)
    app.include_router(me.router)
    app.include_router(titles.router)
    app.include_router(studio.router)
    app.include_router(preview.router)
    app.include_router(webhook.router)
    if settings.app_env == "local":
        # На сервере /assets раздаёт Caddy с того же диска; локально — сам API.
        app.mount("/assets", StaticFiles(directory=settings.assets_dir, check_dir=False))
    return app
