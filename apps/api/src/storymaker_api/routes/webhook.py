import hmac
import logging
from typing import Annotated

from aiogram import Bot, Dispatcher
from aiogram.types import Update
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status

from storymaker_api.config import Settings, get_settings

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/bot/webhook", include_in_schema=False)
async def bot_webhook(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
) -> Response:
    expected = settings.bot_webhook_secret
    if (
        expected is None
        or x_telegram_bot_api_secret_token is None
        or not hmac.compare_digest(x_telegram_bot_api_secret_token, expected.get_secret_value())
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)

    bot: Bot = request.app.state.bot
    dispatcher: Dispatcher = request.app.state.dispatcher
    update = Update.model_validate(await request.json(), context={"bot": bot})
    try:
        await dispatcher.feed_update(bot, update)
    except Exception:
        # Отвечаем 200 в любом случае, иначе Telegram будет бесконечно повторять апдейт.
        logger.exception("failed to handle update %s", update.update_id)
    return Response(status_code=status.HTTP_200_OK)
