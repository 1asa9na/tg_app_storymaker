import logging

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    Message,
    WebAppInfo,
)

from storymaker_api.config import Settings

logger = logging.getLogger(__name__)


async def on_start(message: Message, settings: Settings) -> None:
    text = "Привет! Здесь будут интерактивные истории."
    if not settings.public_url:
        await message.answer(text)
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть", web_app=WebAppInfo(url=settings.public_url))]
        ]
    )
    await message.answer(text, reply_markup=keyboard)


def create_bot(settings: Settings) -> Bot:
    return Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher(settings: Settings) -> Dispatcher:
    # Роутер создаётся заново: один роутер нельзя подключить к двум диспетчерам.
    router = Router()
    router.message.register(on_start, CommandStart())
    dispatcher = Dispatcher(settings=settings)
    dispatcher.include_router(router)
    return dispatcher


async def register_webhook(bot: Bot, dispatcher: Dispatcher, settings: Settings) -> None:
    """Регистрирует вебхук, кнопку меню и команды. Безопасно вызывать при каждом старте."""
    assert settings.public_url and settings.webhook_url and settings.bot_webhook_secret
    await bot.set_webhook(
        url=settings.webhook_url,
        secret_token=settings.bot_webhook_secret.get_secret_value(),
        allowed_updates=dispatcher.resolve_used_update_types(),
    )
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(text="Читать", web_app=WebAppInfo(url=settings.public_url))
    )
    await bot.set_my_commands([BotCommand(command="start", description="Открыть истории")])
    logger.info("webhook registered: %s", settings.webhook_url)
