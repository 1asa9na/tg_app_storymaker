"""Песочница сборки: та же игра, свой слот сохранения, отладка; превью на телефоне; симулятор.

Песочница — сохранение со слотом sandbox:<сборка> у сотрудника. В студии и на телефоне по
превью-ссылке это одно и то же сохранение: можно начать за компьютером и продолжить в Telegram.
"""

import secrets
import time
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from storymaker_api.game.registry import TitleBuild
from storymaker_api.game.scenes import ScenePlayer
from storymaker_api.game.simulator import Settings as SimulationSettings
from storymaker_api.game.simulator import Simulation, report
from storymaker_api.models import PreviewToken, Staff
from storymaker_api.studio.auth import token_hash

PREVIEW_TTL = timedelta(days=7)
#: Предел симуляции из студии: запрос не должен держать сервер дольше пары минут.
MAX_PLAYERS = 300


async def create_preview_token(
    session: AsyncSession, build_id: int, user_id: int, now: datetime
) -> str:
    token = secrets.token_urlsafe(24)
    session.add(
        PreviewToken(
            token_hash=token_hash(token),
            build_id=build_id,
            created_by=user_id,
            expires_at=now + PREVIEW_TTL,
        )
    )
    await session.flush()
    return token


async def preview_build_id(
    session: AsyncSession, token: str, user_id: int, now: datetime
) -> int | None:
    """Сборка по превью-токену — только для команды и пока токен не истёк."""
    found = await session.get(PreviewToken, token_hash(token))
    if found is None or found.expires_at <= now:
        return None
    if await session.scalar(select(Staff.user_id).where(Staff.user_id == user_id)) is None:
        return None
    return found.build_id


def simulate(build: TitleBuild, settings: SimulationSettings) -> dict[str, Any]:
    """Симулятор баланса по сборке (синхронно: запускать в потоке)."""
    started = time.monotonic()
    with ScenePlayer() as player:
        runs = Simulation(build.title, player, settings).run()
    return {
        "report": report(build.title, settings, runs),
        "seconds": round(time.monotonic() - started, 1),
    }
