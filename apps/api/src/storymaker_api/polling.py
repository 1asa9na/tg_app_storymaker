"""Локальный запуск бота без вебхука: python -m storymaker_api.polling

Только для dev-бота: удаляет вебхук у того бота, чей токен в BOT_TOKEN.
"""

import asyncio
import logging

from sqlalchemy.ext.asyncio import async_sessionmaker

from storymaker_api.bot import create_bot, create_dispatcher
from storymaker_api.config import get_settings
from storymaker_api.db import create_engine


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    bot = create_bot(settings)
    engine = create_engine(settings.database_url)
    dispatcher = create_dispatcher(settings, async_sessionmaker(engine, expire_on_commit=False))
    await bot.delete_webhook()
    try:
        await dispatcher.start_polling(bot)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
