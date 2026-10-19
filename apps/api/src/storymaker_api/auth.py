from datetime import UTC, datetime, timedelta
from typing import Annotated

from aiogram.utils.web_app import WebAppUser, safe_parse_webapp_init_data
from fastapi import Depends, Header, HTTPException, status

from storymaker_api.config import Settings, get_settings


def tg_user(
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> WebAppUser:
    """Пользователь Mini App по заголовку `Authorization: tma <initDataRaw>`."""
    scheme, _, raw = (authorization or "").partition(" ")
    if scheme != "tma" or not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing init data")
    try:
        data = safe_parse_webapp_init_data(settings.bot_token.get_secret_value(), raw)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad init data signature") from None
    # Подпись не стареет, поэтому срок жизни initData проверяем сами.
    if datetime.now(UTC) - data.auth_date > timedelta(seconds=settings.init_data_ttl_seconds):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "init data expired")
    if data.user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "no user in init data")
    return data.user
