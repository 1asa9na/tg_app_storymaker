from typing import Annotated

from aiogram.utils.web_app import WebAppUser
from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from storymaker_api.auth import tg_user
from storymaker_api.db import get_session
from storymaker_api.models import User


async def upsert_user(session: AsyncSession, tg: WebAppUser) -> User:
    """Создаёт пользователя при первом входе, дальше обновляет профиль из Telegram."""
    profile = {
        "username": tg.username,
        "first_name": tg.first_name,
        "last_name": tg.last_name,
        "language_code": tg.language_code,
    }
    stmt = (
        insert(User)
        .values(tg_id=tg.id, **profile)
        .on_conflict_do_update(
            index_elements=[User.tg_id], set_={**profile, "last_seen_at": func.now()}
        )
        .returning(User)
    )
    return (await session.scalars(stmt)).one()


async def current_user(
    tg: Annotated[WebAppUser, Depends(tg_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """Пользователь запроса. Профиль обновляет /api/me; здесь — только создание при отсутствии."""
    user = await session.scalar(select(User).where(User.tg_id == tg.id))
    if user is None:
        user = await upsert_user(session, tg)
        await session.commit()
    return user
