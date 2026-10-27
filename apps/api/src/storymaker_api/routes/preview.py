"""Превью сборки на телефоне: песочница сотрудника в Mini App по ссылке из бота.

Вход — initData, как у игрока, но пускает только команду (staff) и только по живому токену.
Сохранение то же, что в песочнице студии для этой сборки.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from storymaker_api import play
from storymaker_api.catalog import Catalog
from storymaker_api.db import get_session
from storymaker_api.models import Build, User
from storymaker_api.routes.game import game_routes
from storymaker_api.studio.sandbox import preview_build_id
from storymaker_api.users import current_user

router = APIRouter(prefix="/api")


async def preview_game(
    token: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(current_user)],
) -> play.Game:
    build_id = await preview_build_id(session, token, user.id, datetime.now(UTC))
    if build_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "preview not found or expired")
    build = await session.get(Build, build_id)
    assert build is not None
    catalog: Catalog = request.app.state.catalog
    loaded = await catalog.build(session, build_id)
    assert loaded is not None
    return play.Game(loaded, build.title_id, play.sandbox_slot(build_id))


game_routes(router, "/preview/{token}", preview_game, current_user)
