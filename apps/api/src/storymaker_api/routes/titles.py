"""API тайтлов для плеера: каталог, игра (routes/game.py), профиль."""

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from storymaker_api import play
from storymaker_api.catalog import Catalog
from storymaker_api.db import get_session
from storymaker_api.models import Save, TitleRow, User
from storymaker_api.progress import get_account, list_achievements
from storymaker_api.routes.game import game_routes, get_now
from storymaker_api.users import current_user

router = APIRouter(prefix="/api")

__all__ = ["get_now", "router"]


def get_catalog(request: Request) -> Catalog:
    return request.app.state.catalog


CatalogDep = Annotated[Catalog, Depends(get_catalog)]
UserDep = Annotated[User, Depends(current_user)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def published_game(slug: str, catalog: CatalogDep, session: SessionDep) -> play.Game:
    found = await catalog.get(session, slug)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "title not found")
    row, build = found
    return play.Game(build, row.id)


# ── Каталог ─────────────────────────────────────────────────────────────


@router.get("/titles")
async def catalog(titles: CatalogDep, user: UserDep, session: SessionDep) -> list[dict[str, Any]]:
    """Опубликованные тайтлы и прогресс игрока в них."""
    rows = await session.execute(
        select(TitleRow.slug, Save.state)
        .join(Save, Save.title_id == TitleRow.id)
        .where(Save.user_id == user.id, Save.slot == play.MAIN)
    )
    saves = {slug: state for slug, state in rows}
    result = []
    for row, build in await titles.published(session):
        slug = row.slug
        state = saves.get(slug)
        result.append(
            {
                "slug": slug,
                "name": build.title.config.name,
                "days": build.title.config.time.days,
                "cover": build.manifest.get("cover", {}).get(slug),
                "save": (
                    {"day": state["day"], "finished": state.get("finished", False)}
                    if state
                    else None
                ),
            }
        )
    return result


# ── Игра ────────────────────────────────────────────────────────────────

game_routes(router, "/titles/{slug}", published_game, current_user)


# ── Профиль ─────────────────────────────────────────────────────────────


class ProfileAchievement(BaseModel):
    key: str
    name: str
    title: str | None = Field(description="slug тайтла; None — достижение платформы")
    unlocked_at: datetime


@router.get("/profile")
async def profile(titles: CatalogDep, user: UserDep, session: SessionDep) -> dict[str, Any]:
    """Глобальный прогресс: уровень, опыт и достижения во всех тайтлах."""
    account = await get_account(session, user.id)
    slugs = dict((await session.execute(select(TitleRow.id, TitleRow.slug))).all())
    achievements = []
    for row in await list_achievements(session, user.id):
        slug = slugs.get(row.title_id) if row.title_id else None
        found = await titles.get(session, slug) if slug else None
        build = found[1] if found else None
        definition = build.title.achievements.get(row.achievement_key) if build else None
        achievements.append(
            ProfileAchievement(
                key=row.achievement_key,
                name=definition.name if definition else row.achievement_key,
                title=slug,
                unlocked_at=row.unlocked_at,
            )
        )
    return {**account.as_dict(), "achievements": jsonable_encoder(achievements)}
