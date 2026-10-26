import logging
from datetime import UTC, datetime

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    MenuButtonWebApp,
    Message,
    WebAppInfo,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from storymaker_api.config import Settings
from storymaker_api.models import User
from storymaker_api.studio.auth import create_login_token, staff_role

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


async def on_studio(
    message: Message, settings: Settings, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """Одноразовая ссылка входа в студию — только для команды (таблица staff)."""
    if message.from_user is None or not settings.studio_url:
        return
    async with sessionmaker() as session:
        user_id = await session.scalar(select(User.id).where(User.tg_id == message.from_user.id))
        if user_id is None or await staff_role(session, user_id) is None:
            await message.answer("Студия доступна только команде.")
            return
        token = await create_login_token(session, user_id, datetime.now(UTC))
        await session.commit()
    url = f"{settings.studio_url.rstrip('/')}/login#{token}"
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Войти в студию", url=url)]]
    )
    # Без превью: Telegram не должен ходить по ссылке сам. Токен — в #фрагменте, его не видит
    # сервер и не пишет в логи; студия отправит его POST-запросом.
    await message.answer(
        "Ссылка действует 10 минут и только один раз.",
        reply_markup=keyboard,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


def create_bot(settings: Settings) -> Bot:
    return Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher(
    settings: Settings, sessionmaker: async_sessionmaker[AsyncSession]
) -> Dispatcher:
    # Роутер создаётся заново: один роутер нельзя подключить к двум диспетчерам.
    router = Router()
    router.message.register(on_start, CommandStart())
    router.message.register(on_studio, Command("studio"))
    dispatcher = Dispatcher(settings=settings, sessionmaker=sessionmaker)
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
