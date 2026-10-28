"""Редактор сцен в студии: исходники по одной сцене и ключи тайтла для подсказок.

Сцену компилирует сама студия, в браузере, тем же движком, что и сборка (packages/engine).
Поэтому сервер отдаёт ей реестр ключей ровно в том виде, в каком его получает компилятор
при сборке, — ошибки в редакторе и при сборке совпадают.
"""

import json
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from storymaker_api.assets import build_manifest, referenced
from storymaker_api.content import current_assets, load_content
from storymaker_api.game.loader import scene_registry
from storymaker_api.models import SceneSource, TitleRow

#: Предел для одной сцены: это текст, сотни килобайт — уже ошибка.
MAX_SOURCE = 200_000

#: Флаги в условиях и эффектах данных: `flag.met_anna`.
_DATA_FLAG = re.compile(r"\bflag\.([a-z][a-z0-9_]*)")
#: Флаги в сценах: `# effect: flag met_anna`, `# effect: unflag met_anna`, `flag("met_anna")`.
_SCENE_FLAG = re.compile(
    r"effect:\s*(?:un)?flag\s+([a-z][a-z0-9_]*)|\bflag\(\s*\"([a-z][a-z0-9_]*)\"\s*\)"
)


class SceneConflictError(Exception):
    """Сцену уже изменил кто-то другой после того, как её открыли."""

    def __init__(self, current: SceneSource | None) -> None:
        super().__init__("scene changed")
        self.current = current


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _names(section: Any) -> dict[str, str]:
    """Ключ → имя для подсказок; без имени — сам ключ."""
    return {
        key: name if isinstance(name := _dict(value).get("name"), str) and name else key
        for key, value in _dict(section).items()
    }


def _flags(sections: dict[str, Any], scenes: dict[str, str]) -> list[str]:
    flags = set(_DATA_FLAG.findall(json.dumps(sections, ensure_ascii=False)))
    start = _dict(_dict(sections.get("config")).get("start")).get("flags")
    if isinstance(start, list):
        flags.update(flag for flag in start if isinstance(flag, str))
    for source in scenes.values():
        for effect, call in _SCENE_FLAG.findall(source):
            flags.add(effect or call)
    return sorted(flags)


async def editor_context(session: AsyncSession, title: TitleRow) -> dict[str, Any]:
    """Всё, что нужно странице сцен: список сцен, реестр компилятора, ключи для подсказок
    и текущие ассеты для превью."""
    content = await load_content(session, title.id)
    sections = content.sections
    versions = await current_assets(session, title.id)
    uploaded = {(kind, key) for kind, key, _ in versions}
    used = referenced(sections, content.scenes)
    locations = _dict(sections.get("locations"))

    def keys(kind: str, extra: set[str]) -> list[str]:
        return sorted({key for k, key in uploaded if k == kind} | extra)

    rows = await session.execute(
        select(SceneSource.key, SceneSource.updated_at)
        .where(SceneSource.title_id == title.id)
        .order_by(SceneSource.key)
    )
    config = _dict(sections.get("config"))
    registry = scene_registry(sections)
    characters = _dict(sections.get("characters"))
    return {
        "scenes": [{"key": key, "updated_at": updated_at} for key, updated_at in rows],
        "registry": registry,
        "characters": {
            key: {
                "name": name,
                "color": _dict(characters[key]).get("color"),
                "emotions": registry["characters"][key],
            }
            for key, name in _names(characters).items()
        },
        "items": _names(sections.get("items")),
        "stats": _names(config.get("stats")),
        "quests": _names(sections.get("quests")),
        "achievements": _names(sections.get("achievements")),
        "flags": _flags(sections, content.scenes),
        "backgrounds": keys(
            "background",
            {b for v in locations.values() if isinstance(b := _dict(v).get("background"), str)},
        ),
        # Музыку и звуки берём ещё и из других сцен: файл часто загружают позже, чем пишут тег.
        "music": keys("music", {key for kind, key in used if kind == "music"}),
        "sfx": keys("sfx", {key for kind, key in used if kind == "sfx"}),
        "locations": {
            key: {"name": name, "background": _dict(locations[key]).get("background")}
            for key, name in _names(locations).items()
        },
        "manifest": build_manifest(versions),
    }


async def read_scene(session: AsyncSession, title: TitleRow, key: str) -> SceneSource | None:
    return await session.scalar(
        select(SceneSource).where(SceneSource.title_id == title.id, SceneSource.key == key)
    )


async def save_scene(
    session: AsyncSession,
    title: TitleRow,
    key: str,
    source: str,
    user_id: int,
    base: datetime | None,
) -> SceneSource:
    """Сохраняет сцену. `base` — время версии, которую правили (None — новая сцена).

    Если с тех пор сцену сохранил кто-то ещё, ничего не пишет: SceneConflictError.
    """
    row = await session.scalar(
        select(SceneSource)
        .where(SceneSource.title_id == title.id, SceneSource.key == key)
        .with_for_update()
    )
    now = datetime.now(UTC)
    if row is None:
        if base is not None:
            raise SceneConflictError(None)
        row = SceneSource(
            title_id=title.id, key=key, source=source, updated_by=user_id, updated_at=now
        )
        session.add(row)
    else:
        if base is None or row.updated_at != base:
            raise SceneConflictError(row)
        row.source = source
        row.updated_by = user_id
        row.updated_at = now
    await session.flush()
    return row


async def delete_scene(session: AsyncSession, title: TitleRow, key: str) -> bool:
    result = await session.execute(
        delete(SceneSource)
        .where(SceneSource.title_id == title.id, SceneSource.key == key)
        .returning(SceneSource.id)
    )
    return result.first() is not None
