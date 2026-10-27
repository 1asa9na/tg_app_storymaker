"""Игра поверх базы: сохранение, действия, сцены — для игроков, песочницы студии и превью.

Действие проходит одной транзакцией: сохранение блокируется (`SELECT … FOR UPDATE`), движок
применяет действие, результат пишется в `action_log`. Повторный запрос с тем же `request_id`
получает записанный ответ и ничего не применяет второй раз.

Сохранение — строка saves (пользователь, тайтл, слот). Слот main — игра; sandbox:<сборка> —
песочница сотрудника: своя история, опыт и достижения аккаунту не начисляются.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from fastapi import HTTPException, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from storymaker_api.game.engine import Action, ActionError, Outcome
from storymaker_api.game.registry import TitleBuild
from storymaker_api.game.state import GameState
from storymaker_api.models import ActionLog, Save, User
from storymaker_api.progress import Account, add_progress, get_account

MAIN = "main"


def sandbox_slot(build_id: int) -> str:
    return f"sandbox:{build_id}"


@dataclass(frozen=True)
class Game:
    """Во что играем: сборка, тайтл в базе и слот сохранения."""

    build: TitleBuild
    title_id: int
    slot: str = MAIN

    @property
    def sandbox(self) -> bool:
        return self.slot != MAIN


class Restart(BaseModel):
    type: Literal["restart"] = "restart"


def refuse(code: str, message: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, {"code": code, "message": message})


def game_data(build: TitleBuild) -> dict[str, Any]:
    """Данные для отображения: имена, картинки, тексты. Без условий, эффектов и событий."""
    title = build.title
    config = title.config
    return {
        "slug": title.id,
        "name": config.name,
        "build": build.build,
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
        # Адреса картинок и звуков; чего здесь нет — плеер рисует заглушкой.
        "assets": build.manifest,
    }


def _load_state(game: Game, save: Save) -> GameState:
    """Состояние из сохранения. Если тайтл обновился — подгоняет его к новой сборке."""
    try:
        state = GameState.model_validate(save.state)
    except ValidationError:
        raise refuse(
            "save_incompatible", "Сохранение не подходит к новой версии тайтла: начните заново"
        ) from None
    if save.build != game.build.build:
        # Правил миграции сохранений пока нет: снимается только то, что безопасно, — сцена,
        # которой больше нет в сборке, уходит из очереди.
        scenes = game.build.title.scenes
        state.pending_scenes = [item for item in state.pending_scenes if item.scene in scenes]
    return state


async def locked_save(
    session: AsyncSession, game: Game, user: User, now: datetime
) -> tuple[Save, GameState]:
    """Сохранение под блокировкой строки; при первом входе создаётся новая игра."""
    stmt = (
        select(Save)
        .where(Save.user_id == user.id, Save.title_id == game.title_id, Save.slot == game.slot)
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
                slot=game.slot,
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


async def _account(session: AsyncSession, game: Game, user: User, state: GameState) -> Account:
    """Аккаунт для экрана. В песочнице — уровень из состояния (его меняет отладка)."""
    if game.sandbox:
        return Account(xp=0, level=state.global_level)
    return await get_account(session, user.id)


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


def _outcome(outcome: Outcome, achievements: list[str]) -> dict[str, Any]:
    return {
        "changes": [{"path": change.path, "delta": change.delta} for change in outcome.changes],
        "scenes": outcome.scenes,
        "xp": outcome.xp,
        "achievements": achievements,
        "quests": [
            {"quest": quest, "status": status_, "stage": stage}
            for quest, status_, stage in outcome.quests
        ],
        "new_day": outcome.new_day,
    }


async def get_state(session: AsyncSession, game: Game, user: User, now: datetime) -> Any:
    save, state = await locked_save(session, game, user, now)
    account = await _account(session, game, user, state)
    view = _view(game, save, _with_level(state, account), account, now)
    await session.commit()
    return view


async def act(
    session: AsyncSession,
    game: Game,
    user: User,
    now: datetime,
    request_id: uuid.UUID,
    revision: int | None,
    action: Action | Restart,
) -> Any:
    save, state = await locked_save(session, game, user, now)
    # Под блокировкой сохранения: параллельный повтор ждёт и видит уже записанный результат.
    logged = await session.scalar(
        select(ActionLog.result).where(
            ActionLog.user_id == user.id,
            ActionLog.title_id == game.title_id,
            ActionLog.slot == game.slot,
            ActionLog.request_id == request_id,
        )
    )
    if logged is not None:
        await session.rollback()
        return logged
    if revision is not None and revision != save.revision:
        await session.rollback()
        raise refuse("stale", "Игра изменилась в другом окне: обновите экран")

    account = await _account(session, game, user, state)
    if isinstance(action, Restart):
        outcome = Outcome(state=game.build.engine.new_game(now))
        if game.sandbox:
            outcome.state.global_level = state.global_level
    else:
        try:
            outcome = game.build.engine.apply(_with_level(state, account), action, now)
        except ActionError as error:
            await session.rollback()
            raise refuse(error.code, error.message) from None

    if game.sandbox:
        # Песочница не трогает настоящий аккаунт: опыт и достижения только показываются.
        achievements = outcome.achievements
    else:
        account, achievements = await add_progress(
            session, user.id, game.title_id, outcome.xp, outcome.achievements
        )
    _store(save, game, outcome.state, now)
    result = {
        **_view(game, save, _with_level(outcome.state, account), account, now),
        "outcome": _outcome(outcome, achievements),
    }
    session.add(
        ActionLog(
            user_id=user.id,
            title_id=game.title_id,
            slot=game.slot,
            request_id=request_id,
            revision=save.revision,
            action=action.model_dump(mode="json"),
            result=result,
        )
    )
    await session.commit()
    return result


async def scene(
    session: AsyncSession, game: Game, user: User, now: datetime, key: str
) -> dict[str, Any]:
    """Скомпилированная сцена — только та, которую игрок сейчас должен смотреть."""
    save, state = await locked_save(session, game, user, now)
    await session.commit()
    if not state.pending_scenes or state.pending_scenes[0].scene != key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "scene is not playing")
    return {"key": key, "revision": save.revision, "json": game.build.title.scenes[key].json_}


# ── Только песочница ────────────────────────────────────────────────────


def check_state(game: Game, state: GameState) -> list[str]:
    """Состояние из отладки должно ссылаться только на то, что есть в сборке."""
    title = game.build.title
    problems: list[str] = []
    if not 0 <= state.slot < len(title.slot_ids):
        problems.append(f"нет части дня с номером {state.slot}")
    if state.day < 1:
        problems.append("день начинается с 1")
    if state.location is not None and state.location not in title.locations:
        problems.append(f"нет локации {state.location}")
    if set(state.resources) != set(title.config.resources):
        problems.append("ресурсы должны совпадать с title.yaml")
    for key in state.items:
        if key not in title.items:
            problems.append(f"нет предмета {key}")
    for key in state.affection:
        if key not in title.characters:
            problems.append(f"нет персонажа {key}")
    for key in state.stats:
        if key not in title.config.stats:
            problems.append(f"нет характеристики {key}")
    for key, quest in state.quests.items():
        definition = title.quests.get(key)
        if definition is None:
            problems.append(f"нет квеста {key}")
        elif not 0 <= quest.stage < len(definition.stages):
            problems.append(f"у квеста {key} нет этапа номер {quest.stage}")
    for pending in state.pending_scenes:
        if pending.scene not in title.scenes:
            problems.append(f"нет сцены {pending.scene}")
    return problems


async def set_state(
    session: AsyncSession, game: Game, user: User, now: datetime, state: GameState
) -> Any:
    """Отладка песочницы: заменить сохранение целиком (день, ресурсы, предметы, квесты…)."""
    assert game.sandbox, "править состояние можно только в песочнице"
    problems = check_state(game, state)
    if problems:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, {"errors": problems})
    save, _ = await locked_save(session, game, user, now)
    state = state.model_copy(update={"title": game.build.title.id})
    _store(save, game, state, now)
    account = await _account(session, game, user, state)
    view = _view(game, save, state, account, now)
    await session.commit()
    return view


async def action_log(
    session: AsyncSession, game: Game, user: User, limit: int = 50
) -> list[dict[str, Any]]:
    """Последние действия в сохранении — для панели отладки."""
    rows = await session.scalars(
        select(ActionLog)
        .where(
            ActionLog.user_id == user.id,
            ActionLog.title_id == game.title_id,
            ActionLog.slot == game.slot,
        )
        .order_by(ActionLog.id.desc())
        .limit(limit)
    )
    return [
        {
            "at": row.created_at,
            "revision": row.revision,
            "action": row.action,
            "outcome": row.result.get("outcome"),
            "time": row.result.get("time"),
        }
        for row in rows
    ]
