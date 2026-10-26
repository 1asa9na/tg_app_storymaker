"""Контент тайтлов в базе: импорт файлов геймдизайнера, сборки, публикация.

Тайтл в базе — документы (по сущности на строку) и исходники сцен. Сборка собирает их тем же
загрузчиком, что и папку с YAML (game/loader.py), и сохраняет результат целиком; игроки играют
активную сборку тайтла.
"""

import asyncio
import io
import zipfile
from dataclasses import dataclass, field
from typing import Any

import yaml
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from storymaker_api.game.loader import SECTIONS, Files, assemble, parse_files
from storymaker_api.game.registry import TitleBuild, dump_title
from storymaker_api.game.schema import Title
from storymaker_api.models import Build, SceneSource, TitleDocument, TitleRow

#: Разделы из одного документа (ключ main), остальные — словарь сущностей.
SINGLE = {"config", "map"}
MAIN = "main"


async def get_or_create_title(session: AsyncSession, slug: str, name: str) -> TitleRow:
    title = await session.scalar(select(TitleRow).where(TitleRow.slug == slug))
    if title is None:
        sort = await session.scalar(select(func.coalesce(func.max(TitleRow.sort), -1) + 1))
        title = TitleRow(slug=slug, name=name, sort=sort or 0)
        session.add(title)
        await session.flush()
    return title


async def import_files(
    session: AsyncSession, title: TitleRow, files: Files, user_id: int | None
) -> list[str]:
    """Заменяет документы и сцены тайтла содержимым файлов. Возвращает ошибки разбора."""
    parsed = parse_files(files)
    if parsed.errors:
        return parsed.errors
    await session.execute(delete(TitleDocument).where(TitleDocument.title_id == title.id))
    await session.execute(delete(SceneSource).where(SceneSource.title_id == title.id))
    for section, data in parsed.sections.items():
        items = {MAIN: data} if section in SINGLE else data
        for key, value in items.items():
            session.add(
                TitleDocument(
                    title_id=title.id, kind=section, key=str(key), data=value, updated_by=user_id
                )
            )
    for key, source in parsed.scenes.items():
        session.add(SceneSource(title_id=title.id, key=key, source=source, updated_by=user_id))
    name = parsed.sections.get("config", {}).get("name")
    if isinstance(name, str) and name:
        title.name = name
    await session.flush()
    return []


@dataclass
class Content:
    sections: dict[str, Any] = field(default_factory=dict)
    scenes: dict[str, str] = field(default_factory=dict)


async def load_content(session: AsyncSession, title_id: int) -> Content:
    content = Content()
    documents = await session.scalars(
        select(TitleDocument).where(TitleDocument.title_id == title_id).order_by(TitleDocument.id)
    )
    for document in documents:
        if document.kind in SINGLE:
            content.sections[document.kind] = document.data
        else:
            content.sections.setdefault(document.kind, {})[document.key] = document.data
    scenes = await session.scalars(
        select(SceneSource).where(SceneSource.title_id == title_id).order_by(SceneSource.key)
    )
    content.scenes = {scene.key: scene.source for scene in scenes}
    return content


def export_zip(slug: str, content: Content) -> bytes:
    """Тайтл архивом в формате папки геймдизайнера: его можно править и загрузить обратно."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for section, file in SECTIONS.items():
            if section in content.sections:
                text = yaml.safe_dump(
                    content.sections[section], allow_unicode=True, sort_keys=False, width=100
                )
                archive.writestr(f"{slug}/{file}", text)
        for key, source in content.scenes.items():
            archive.writestr(f"{slug}/scenes/{key}.ink", source)
    return buffer.getvalue()


@dataclass
class BuildResult:
    build: Build | None
    errors: list[str]
    warnings: list[str]


async def create_build(
    session: AsyncSession, title: TitleRow, user_id: int | None, notes: str = ""
) -> BuildResult:
    """Собирает тайтл из базы. Ошибки — сборка не сохраняется."""
    content = await load_content(session, title.id)
    if "config" not in content.sections:
        return BuildResult(None, ["нет настроек тайтла (title.yaml): сначала импортируйте"], [])
    # Компиляция сцен идёт в Node — не держим event loop.
    result = await asyncio.to_thread(assemble, title.slug, content.sections, content.scenes)
    if result.errors or result.title is None:
        return BuildResult(None, result.errors, result.warnings)
    data = dump_title(result.title)
    version = await session.scalar(
        select(func.coalesce(func.max(Build.version), 0) + 1).where(Build.title_id == title.id)
    )
    build = Build(
        title_id=title.id,
        version=version or 1,
        hash=TitleBuild.from_json(data).build,
        data=data,
        warnings=result.warnings,
        notes=notes,
        created_by=user_id,
    )
    session.add(build)
    await session.flush()
    return BuildResult(build, [], result.warnings)


def lost_ids(old: Title, new: Title) -> list[str]:
    """Ключи, которые были в старой сборке и пропали в новой: на них ссылаются сохранения."""
    lost: list[str] = []

    def compare(label: str, before: object, after: object) -> None:
        assert isinstance(before, dict) and isinstance(after, dict)
        lost.extend(f"{label} {key}" for key in before if key not in after)

    compare("ресурс", old.config.resources, new.config.resources)
    compare("характеристика", old.config.stats, new.config.stats)
    for section, label in (
        ("characters", "персонаж"),
        ("locations", "локация"),
        ("activities", "занятие"),
        ("items", "предмет"),
        ("quests", "квест"),
        ("events", "событие"),
        ("achievements", "достижение"),
        ("scenes", "сцена"),
    ):
        compare(label, getattr(old, section), getattr(new, section))
    for key, quest in old.quests.items():
        if key in new.quests:
            stages = [stage.id for stage in new.quests[key].stages]
            for index, stage in enumerate(quest.stages):
                # Сохранение помнит номер этапа: удаление или перестановка его сдвинут.
                if index >= len(stages) or stages[index] != stage.id:
                    lost.append(f"этап квеста {key}: {stage.id}")
                    break
    return lost


async def publish(
    session: AsyncSession, title: TitleRow, build: Build, *, force: bool = False
) -> list[str]:
    """Делает сборку активной и тайтл видимым. Возвращает потерянные ключи, если не force."""
    if title.active_build_id is not None and title.active_build_id != build.id and not force:
        active = await session.get(Build, title.active_build_id)
        if active is not None:
            lost = lost_ids(
                Title.model_validate_json(active.data), Title.model_validate_json(build.data)
            )
            if lost:
                return lost
    title.active_build_id = build.id
    title.status = "published"
    await session.flush()
    return []
