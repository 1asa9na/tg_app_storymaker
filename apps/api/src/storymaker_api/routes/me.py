from typing import Annotated

from aiogram.utils.web_app import WebAppUser
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from storymaker_api.auth import tg_user
from storymaker_api.db import get_session
from storymaker_api.models import User

router = APIRouter(prefix="/api")


class MeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tg_id: int
    first_name: str
    username: str | None
    language_code: str | None


@router.get("/me")
async def me(
    tg: Annotated[WebAppUser, Depends(tg_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MeResponse:
    """Текущий пользователь. При первом запросе создаётся, дальше обновляется профиль."""
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
    user = (await session.scalars(stmt)).one()
    await session.commit()
    return MeResponse.model_validate(user)
