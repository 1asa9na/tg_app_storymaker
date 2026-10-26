"""API тайтлов для плеера: каталог, состояние, действия, сцены, профиль.

Действие проходит одной транзакцией: сохранение блокируется (`SELECT … FOR UPDATE`), движок
применяет действие, результат пишется в `action_log`. Повторный запрос с тем же `request_id`
получает записанный ответ и ничего не применяет второй раз.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from storymaker_api.catalog import Catalog
from storymaker_api.db import get_session
from storymaker_api.game.engine import Action, ActionError, Outcome
from storymaker_api.game.registry import TitleBuild
from storymaker_api.game.state import GameState
from storymaker_api.models import ActionLog, Save, TitleRow, User
from storymaker_api.progress import Account, add_progress, get_account, list_achievements
from storymaker_api.users import current_user

router = APIRouter(prefix="/api")

MAIN = "main"


def get_now() -> datetime:
    return datetime.now(UTC)


def get_catalog(request: Request) -> Catalog:
    return request.app.state.catalog


CatalogDep = Annotated[Catalog, Depends(get_catalog)]


class Game:
    """Тайтл запроса: сборка и id в базе."""

    def __init__(self, build: TitleBuild, title_id: int) -> None:
        self.build = build
        self.title_id = title_id


async def get_game(
    slug: str, catalog: CatalogDep, session: Annotated[AsyncSession, Depends(get_session)]
) -> Game:
    found = await catalog.get(session, slug)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "title not found")
    row, build = found
    return Game(build, row.id)


UserDep = Annotated[User, Depends(current_user)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
GameDep = Annotated[Game, Depends(get_game)]
NowDep = Annotated[datetime, Depends(get_now)]


def _refuse(code: str, message: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, {"code": code, "message": message})


def _load_state(game: Game, save: Save) -> GameState:
    """Состояние из сохранения. Если тайтл обновился — подгоняет его к новой сборке."""
    try:
        state = GameState.model_validate(save.state)
    except ValidationError:
        raise _refuse(
            "save_incompatible", "Сохранение не подходит к новой версии тайтла: начните заново"
        ) from None
    if save.build != game.build.build:
        # Полноценные правила миграции появятся с публикацией (этап 3). Пока — только то,
        # что безопасно: сцена, которой больше нет, снимается из очереди.
        scenes = game.build.title.scenes
        state.pending_scenes = [item for item in state.pending_scenes if item.scene in scenes]
    return state


async def _locked_save(
    session: AsyncSession, game: Game, user: User, now: datetime
) -> tuple[Save, GameState]:
    """Сохранение под блокировкой строки; при первом входе создаётся новая игра."""
    stmt = (
        select(Save)
        .where(Save.user_id == user.id, Save.title_id == game.title_id, Save.slot == MAIN)
        .with_for_update()
    )
    save = await session.scalar(stmt)
    if save is None:
        state = game.build.engine.new_game(now)
        await session.execute(
            insert(Save)
            .values(
                user_id=user.id,
                title_id=game.title_id,
                slot=MAIN,
                build=game.build.build,
                state=state.model_dump(mode="json"),
            )
            .on_conflict_do_nothing()
        )
        save = await session.scalar(stmt.execution_options(populate_existing=True))
        assert save is not None
    return save, _load_state(game, save)


def _store(save: Save, game: Game, state: GameState, now: datetime) -> None:
    save.state = state.model_dump(mode="json")
    save.build = game.build.build
    save.revision += 1
    save.updated_at = now


def _with_level(state: GameState, account: Account) -> GameState:
    return state.model_copy(update={"global_level": account.level})


def _view(game: Game, save: Save, state: GameState, account: Account, now: datetime) -> Any:
    return jsonable_encoder(
        {
            "revision": save.revision,
            "account": account.as_dict(),
            **game.build.engine.view(state, now),
        }
    )


def _outcome(outcome: Outcome, unlocked: list[str]) -> dict[str, Any]:
    return {
        "changes": [{"path": change.path, "delta": change.delta} for change in outcome.changes],
        "scenes": outcome.scenes,
        "xp": outcome.xp,
        "achievements": unlocked,
        "quests": [
            {"quest": quest, "status": status_, "stage": stage}
            for quest, status_, stage in outcome.quests
        ],
        "new_day": outcome.new_day,
    }


# ── Каталог ─────────────────────────────────────────────────────────────


@router.get("/titles")
async def catalog(titles: CatalogDep, user: UserDep, session: SessionDep) -> list[dict[str, Any]]:
    """Опубликованные тайтлы и прогресс игрока в них."""
    rows = await session.execute(
        select(TitleRow.slug, Save.state)
        .join(Save, Save.title_id == TitleRow.id)
        .where(Save.user_id == user.id, Save.slot == MAIN)
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
                "save": (
                    {"day": state["day"], "finished": state.get("finished", False)}
                    if state
                    else None
                ),
            }
        )
    return result


@router.get("/titles/{slug}/game")
async def game_data(game: GameDep) -> dict[str, Any]:
    """Данные для отображения: имена, картинки, тексты. Без условий, эффектов и событий."""
    title = game.build.title
    config = title.config
    return {
        "slug": title.id,
        "name": config.name,
        "build": game.build.build,
        "time": {
            "slots": [slot.model_dump() for slot in config.time.slots],
            "days": config.time.days,
            "week": config.time.week,
        },
        "resources": {
            key: {"name": resource.name, "max": resource.max}
            for key, resource in config.resources.items()
        },
        "stats": {
            key: {"name": stat.name, "min": stat.min, "max": stat.max}
            for key, stat in config.stats.items()
        },
        "characters": {
            key: {
                "name": character.name,
                "color": character.color,
                "emotions": character.emotions,
                "romance": character.romance,
                "levels": [level.model_dump() for level in character.levels],
            }
            for key, character in title.characters.items()
        },
        "gifts_per_day": config.gifts.per_character_per_day,
        "map": title.map.model_dump(),
        "locations": {
            key: {"name": location.name, "background": location.background}
            for key, location in title.locations.items()
        },
        "items": {
            key: item.model_dump(include={"name", "description", "icon", "kind"})
            for key, item in title.items.items()
        },
        "quests": {
            key: {
                "name": quest.name,
                "stages": [{"id": stage.id, "journal": stage.journal} for stage in quest.stages],
            }
            for key, quest in title.quests.items()
        },
        "achievements": {
            key: achievement.model_dump() for key, achievement in title.achievements.items()
        },
    }


# ── Игра ────────────────────────────────────────────────────────────────


@router.get("/titles/{slug}/state")
async def get_state(game: GameDep, user: UserDep, session: SessionDep, now: NowDep) -> Any:
    """Сохранение и всё, что нужно экрану. Первый запрос начинает игру."""
    save, state = await _locked_save(session, game, user, now)
    account = await get_account(session, user.id)
    view = _view(game, save, _with_level(state, account), account, now)
    await session.commit()
    return view


class ActionRequest(BaseModel):
    request_id: uuid.UUID
    #: Ревизия, которую видит клиент. Если сохранение уже ушло вперёд (вторая вкладка,
    #: другое устройство), действие не применяется.
    revision: int | None = None
    action: Action


class RestartRequest(BaseModel):
    request_id: uuid.UUID
    revision: int | None = None


class _Restart(BaseModel):
    type: Literal["restart"] = "restart"


async def _act(
    session: AsyncSession,
    game: Game,
    user: User,
    now: datetime,
    request_id: uuid.UUID,
    revision: int | None,
    action: Action | _Restart,
) -> Any:
    save, state = await _locked_save(session, game, user, now)
    # Под блокировкой сохранения: параллельный повтор ждёт и видит уже записанный результат.
    logged = await session.scalar(
        select(ActionLog.result).where(
            ActionLog.user_id == user.id,
            ActionLog.title_id == game.title_id,
            ActionLog.slot == MAIN,
            ActionLog.request_id == request_id,
        )
    )
    if logged is not None:
        await session.rollback()
        return logged
    if revision is not None and revision != save.revision:
        await session.rollback()
        raise _refuse("stale", "Игра изменилась в другом окне: обновите экран")

    account = await get_account(session, user.id)
    if isinstance(action, _Restart):
        state = game.build.engine.new_game(now)
        outcome = Outcome(state=state)
    else:
        try:
            outcome = game.build.engine.apply(_with_level(state, account), action, now)
        except ActionError as error:
            await session.rollback()
            raise _refuse(error.code, error.message) from None

    account, unlocked = await add_progress(
        session, user.id, game.title_id, outcome.xp, outcome.achievements
    )
    _store(save, game, outcome.state, now)
    result = {
        **_view(game, save, _with_level(outcome.state, account), account, now),
        "outcome": _outcome(outcome, unlocked),
    }
    session.add(
        ActionLog(
            user_id=user.id,
            title_id=game.title_id,
            slot=MAIN,
            request_id=request_id,
            revision=save.revision,
            action=action.model_dump(mode="json"),
            result=result,
        )
    )
    await session.commit()
    return result


@router.post("/titles/{slug}/actions")
async def act(
    body: ActionRequest, game: GameDep, user: UserDep, session: SessionDep, now: NowDep
) -> Any:
    """Действие игрока: переход, занятие, подарок, предмет, сон или завершение сцены."""
    return await _act(session, game, user, now, body.request_id, body.revision, body.action)


@router.post("/titles/{slug}/restart")
async def restart(
    body: RestartRequest, game: GameDep, user: UserDep, session: SessionDep, now: NowDep
) -> Any:
    """Начать тайтл заново. Опыт и достижения аккаунта остаются."""
    return await _act(session, game, user, now, body.request_id, body.revision, _Restart())


@router.get("/titles/{slug}/scenes/{key}")
async def scene(
    key: str, game: GameDep, user: UserDep, session: SessionDep, now: NowDep
) -> dict[str, Any]:
    """Скомпилированная сцена — только та, которую игрок сейчас должен смотреть."""
    save, state = await _locked_save(session, game, user, now)
    await session.commit()
    if not state.pending_scenes or state.pending_scenes[0].scene != key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "scene is not playing")
    return {"key": key, "revision": save.revision, "json": game.build.title.scenes[key].json_}


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
