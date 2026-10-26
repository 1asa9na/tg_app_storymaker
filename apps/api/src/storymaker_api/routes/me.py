from typing import Annotated

from aiogram.utils.web_app import WebAppUser
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from storymaker_api.auth import tg_user
from storymaker_api.db import get_session
from storymaker_api.progress import get_account
from storymaker_api.users import upsert_user

router = APIRouter(prefix="/api")


class MeResponse(BaseModel):
    id: int
    tg_id: int
    first_name: str
    username: str | None
    language_code: str | None
    level: int
    xp: int


@router.get("/me")
async def me(
    tg: Annotated[WebAppUser, Depends(tg_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MeResponse:
    """Текущий пользователь. При первом запросе создаётся, дальше обновляется профиль."""
    user = await upsert_user(session, tg)
    await session.commit()
    account = await get_account(session, user.id)
    return MeResponse(
        id=user.id,
        tg_id=user.tg_id,
        first_name=user.first_name,
        username=user.username,
        language_code=user.language_code,
        level=account.level,
        xp=account.xp,
    )
