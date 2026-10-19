"""Локальный запуск бота без вебхука: python -m storymaker_api.polling

Только для dev-бота: удаляет вебхук у того бота, чей токен в BOT_TOKEN.
"""

import asyncio
import logging

from storymaker_api.bot import create_bot, create_dispatcher
from storymaker_api.config import get_settings


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    bot = create_bot(settings)
    dispatcher = create_dispatcher(settings)
    await bot.delete_webhook()
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
