"""Редактирование данных тайтла в студии: по одной сущности (персонаж, локация, занятие…).

Сущность проверяется своей схемой сразу при сохранении — ошибка поля не даст сохранить.
Ссылки между сущностями проверяются по всему тайтлу и возвращаются списком: черновик может
временно ссылаться на то, чего ещё нет, но сборка с такими ошибками не пройдёт.
"""

from typing import Any

from pydantic import BaseModel, TypeAdapter, ValidationError
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from storymaker_api.content import MAIN, SINGLE, load_content
from storymaker_api.game.loader import SECTIONS, assemble, error_message
from storymaker_api.game.schema import (
    Achievement,
    Activity,
    Character,
    Config,
    Event,
    Id,
    Item,
    Location,
    Map,
    Quest,
    normalize_trigger,
)
from storymaker_api.models import TitleDocument, TitleRow

#: Раздел → схема одной сущности.
MODELS: dict[str, type[BaseModel]] = {
    "config": Config,
    "characters": Character,
    "map": Map,
    "locations": Location,
    "activities": Activity,
    "items": Item,
    "quests": Quest,
    "events": Event,
    "achievements": Achievement,
}


def schemas() -> dict[str, Any]:
    """JSON Schema сущностей — по ним студия строит формы."""
    return {kind: model.model_json_schema() for kind, model in MODELS.items()}


def validate_entity(kind: str, key: str, data: Any) -> list[str]:
    """Ошибки одной сущности: «cost → energy: ожидается целое число»."""
    errors: list[str] = []
    if kind in SINGLE and key != MAIN:
        errors.append(f"у раздела {SECTIONS[kind]} один документ с ключом {MAIN}")
    if kind not in SINGLE:
        try:
            TypeAdapter(Id).validate_python(key)
        except ValidationError:
            errors.append("ключ — латиница в нижнем регистре, цифры и _, с буквы")
    try:
        MODELS[kind].model_validate(data)
    except ValidationError as error:
        for problem in error.errors():
            where = " → ".join(str(part) for part in problem["loc"]) or "данные"
            errors.append(f"{where}: {error_message(problem)}")
    return errors


def _normalize(kind: str, data: Any) -> Any:
    """Короткая запись триггера (day_start, {activity: x}) — в полную, как в форме."""
    if kind == "events" and isinstance(data, dict) and "trigger" in data:
        return {**data, "trigger": normalize_trigger(data["trigger"])}
    return data


def _scene_stub(sources: dict[str, str], registry: dict[str, Any]) -> dict[str, Any]:
    """Сцены для быстрой проверки ссылок: без компиляции (её делает сборка)."""
    del registry
    return {"scenes": {key: {"json": "{}", "effects": []} for key in sources}}


async def problems(session: AsyncSession, title: TitleRow) -> dict[str, list[str]]:
    """Ошибки и предупреждения данных тайтла целиком, без компиляции сцен."""
    content = await load_content(session, title.id)
    if "config" not in content.sections:
        return {"errors": ["нет настроек тайтла"], "warnings": []}
    result = assemble(title.slug, content.sections, content.scenes, _scene_stub)
    return {"errors": result.errors, "warnings": result.warnings}


async def read_documents(session: AsyncSession, title: TitleRow) -> dict[str, Any]:
    content = await load_content(session, title.id)
    sections: dict[str, Any] = {}
    for kind in MODELS:
        data = content.sections.get(kind)
        if kind in SINGLE:
            sections[kind] = data
        else:
            sections[kind] = {key: _normalize(kind, value) for key, value in (data or {}).items()}
    return {"sections": sections, "scenes": sorted(content.scenes)}


async def save_document(
    session: AsyncSession, title: TitleRow, kind: str, key: str, data: Any, user_id: int
) -> None:
    await session.execute(
        insert(TitleDocument)
        .values(title_id=title.id, kind=kind, key=key, data=data, updated_by=user_id)
        .on_conflict_do_update(
            index_elements=[TitleDocument.title_id, TitleDocument.kind, TitleDocument.key],
            set_={"data": data, "updated_by": user_id},
        )
    )
    if kind == "config" and isinstance(data, dict) and isinstance(data.get("name"), str):
        title.name = data["name"]


async def delete_document(session: AsyncSession, title: TitleRow, kind: str, key: str) -> bool:
    result = await session.execute(
        delete(TitleDocument)
        .where(
            TitleDocument.title_id == title.id,
            TitleDocument.kind == kind,
            TitleDocument.key == key,
        )
        .returning(TitleDocument.id)
    )
    return result.first() is not None


async def document_exists(session: AsyncSession, title: TitleRow, kind: str, key: str) -> bool:
    return (
        await session.scalar(
            select(TitleDocument.id).where(
                TitleDocument.title_id == title.id,
                TitleDocument.kind == kind,
                TitleDocument.key == key,
            )
        )
    ) is not None
