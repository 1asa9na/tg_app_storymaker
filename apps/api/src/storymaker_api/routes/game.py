"""Игровые маршруты: одни и те же для плеера, песочницы студии и превью на телефоне.

Каждый потребитель подключает их со своими зависимостями: как найти сборку (опубликованная,
выбранная в студии, из превью-токена) и как узнать пользователя (initData или cookie студии).
"""

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from storymaker_api import play
from storymaker_api.db import get_session
from storymaker_api.game.engine import Action
from storymaker_api.game.state import GameState
from storymaker_api.models import User


def get_now() -> datetime:
    return datetime.now(UTC)


class ActionRequest(BaseModel):
    request_id: uuid.UUID
    #: Ревизия, которую видит клиент. Если сохранение уже ушло вперёд (вторая вкладка,
    #: другое устройство), действие не применяется.
    revision: int | None = None
    action: Action


class RestartRequest(BaseModel):
    request_id: uuid.UUID
    revision: int | None = None


class StateRequest(BaseModel):
    state: GameState


def game_routes(
    router: APIRouter,
    prefix: str,
    game: Callable[..., Awaitable[play.Game]],
    user: Callable[..., Awaitable[User]],
    *,
    debug: bool = False,
) -> None:
    """Регистрирует game, state, actions, restart, scenes (и отладку песочницы, если debug)."""

    @router.get(f"{prefix}/game")
    async def game_data(current: Annotated[play.Game, Depends(game)]) -> dict[str, Any]:
        """Данные для отображения: имена, картинки, тексты. Без условий и событий."""
        return play.game_data(current.build)

    @router.get(f"{prefix}/state")
    async def state(
        current: Annotated[play.Game, Depends(game)],
        who: Annotated[User, Depends(user)],
        session: Annotated[AsyncSession, Depends(get_session)],
        now: Annotated[datetime, Depends(get_now)],
    ) -> Any:
        """Сохранение и всё, что нужно экрану. Первый запрос начинает игру."""
        return await play.get_state(session, current, who, now)

    @router.post(f"{prefix}/actions")
    async def act(
        body: ActionRequest,
        current: Annotated[play.Game, Depends(game)],
        who: Annotated[User, Depends(user)],
        session: Annotated[AsyncSession, Depends(get_session)],
        now: Annotated[datetime, Depends(get_now)],
    ) -> Any:
        """Действие игрока: переход, занятие, подарок, предмет, сон или завершение сцены."""
        return await play.act(
            session, current, who, now, body.request_id, body.revision, body.action
        )

    @router.post(f"{prefix}/restart")
    async def restart(
        body: RestartRequest,
        current: Annotated[play.Game, Depends(game)],
        who: Annotated[User, Depends(user)],
        session: Annotated[AsyncSession, Depends(get_session)],
        now: Annotated[datetime, Depends(get_now)],
    ) -> Any:
        """Начать заново. Опыт и достижения аккаунта остаются."""
        return await play.act(
            session, current, who, now, body.request_id, body.revision, play.Restart()
        )

    @router.get(f"{prefix}/scenes/{{key}}")
    async def scene(
        key: str,
        current: Annotated[play.Game, Depends(game)],
        who: Annotated[User, Depends(user)],
        session: Annotated[AsyncSession, Depends(get_session)],
        now: Annotated[datetime, Depends(get_now)],
    ) -> dict[str, Any]:
        """Скомпилированная сцена — только та, которую сейчас нужно смотреть."""
        return await play.scene(session, current, who, now, key)

    if not debug:
        return

    @router.put(f"{prefix}/debug/state")
    async def set_state(
        body: StateRequest,
        current: Annotated[play.Game, Depends(game)],
        who: Annotated[User, Depends(user)],
        session: Annotated[AsyncSession, Depends(get_session)],
        now: Annotated[datetime, Depends(get_now)],
    ) -> Any:
        """Песочница: заменить сохранение — день, время, ресурсы, предметы, квесты, флаги."""
        return await play.set_state(session, current, who, now, body.state)

    @router.get(f"{prefix}/debug/log")
    async def log(
        current: Annotated[play.Game, Depends(game)],
        who: Annotated[User, Depends(user)],
        session: Annotated[AsyncSession, Depends(get_session)],
    ) -> list[dict[str, Any]]:
        """Последние действия в песочнице."""
        return await play.action_log(session, current, who)
