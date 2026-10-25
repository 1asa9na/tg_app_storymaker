"""Загрузка тайтла из папки с YAML-файлами и сценами — рабочий формат геймдизайнера до студии.

content/titles/<slug>/
  title.yaml         настройки: время, ресурсы, характеристики, старт
  characters.yaml    персонажи и их расписания
  map.yaml           карта и точки локаций
  locations.yaml
  activities.yaml
  items.yaml
  quests.yaml
  events.yaml
  achievements.yaml
  scenes/*.ink
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from storymaker_api.game.scenes import compile_scenes
from storymaker_api.game.schema import Title
from storymaker_api.game.validation import check_title

#: Раздел тайтла → файл.
SECTIONS = {
    "config": "title.yaml",
    "characters": "characters.yaml",
    "map": "map.yaml",
    "locations": "locations.yaml",
    "activities": "activities.yaml",
    "items": "items.yaml",
    "quests": "quests.yaml",
    "events": "events.yaml",
    "achievements": "achievements.yaml",
}
KEY = re.compile(r"^[a-z][a-z0-9_]*$")

#: Понятные сообщения вместо английских текстов Pydantic.
MESSAGES = {
    "missing": "обязательное поле",
    "extra_forbidden": "неизвестное поле",
    "int_type": "ожидается целое число",
    "int_parsing": "ожидается целое число",
    "int_from_float": "ожидается целое число",
    "float_type": "ожидается число",
    "float_parsing": "ожидается число",
    "bool_type": "ожидается true или false",
    "bool_parsing": "ожидается true или false",
    "string_type": "ожидается строка",
    "string_pattern_mismatch": "ожидается ключ латиницей в нижнем регистре: a-z, 0-9, _",
    "dict_type": "ожидается словарь (ключ: значение)",
    "list_type": "ожидается список",
    "literal_error": "недопустимое значение",
    "greater_than": "значение слишком маленькое",
    "greater_than_equal": "значение слишком маленькое",
    "less_than_equal": "значение слишком большое",
    "too_short": "список не должен быть пустым",
}

Compiler = Callable[[dict[str, str], dict[str, Any]], dict[str, Any]]


@dataclass
class LoadResult:
    title: Title | None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _where(location: tuple[int | str, ...]) -> str:
    section, *path = location
    file = SECTIONS.get(str(section), str(section))
    return " → ".join([file, *(str(part) for part in path)])


def _message(error: Any) -> str:
    text = MESSAGES.get(error["type"])
    if error["type"] == "value_error":
        text = str(error["msg"]).removeprefix("Value error, ")
    return text or str(error["msg"])


def load_title(directory: Path, compiler: Compiler = compile_scenes) -> LoadResult:
    result = LoadResult(title=None)
    if not (directory / "title.yaml").exists():
        result.errors.append(f"{directory}: нет title.yaml")
        return result

    raw: dict[str, Any] = {"id": directory.name}
    for section, file in SECTIONS.items():
        path = directory / file
        if not path.exists():
            continue
        try:
            raw[section] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as error:
            result.errors.append(f"{file}: ошибка YAML: {error}")
    if result.errors:
        return result

    try:
        title = Title.model_validate(raw)
    except ValidationError as error:
        for problem in error.errors():
            result.errors.append(f"{_where(problem['loc'])}: {_message(problem)}")
        return result

    sources: dict[str, str] = {}
    for path in sorted((directory / "scenes").glob("*.ink")):
        if KEY.match(path.stem):
            sources[path.stem] = path.read_text(encoding="utf-8")
        else:
            result.errors.append(f"scenes/{path.name}: имя файла — ключ латиницей: a-z, 0-9, _")
    if sources:
        registry = {
            "characters": {key: list(char.emotions) for key, char in title.characters.items()},
            "items": list(title.items),
            "stats": list(title.config.stats),
            "quests": list(title.quests),
            "achievements": list(title.achievements),
        }
        compiled = compiler(sources, registry)
        for key, diagnostics in compiled.get("diagnostics", {}).items():
            for diagnostic in diagnostics:
                line = f":{diagnostic['line']}" if diagnostic.get("line") else ""
                message = f"scenes/{key}.ink{line}: {diagnostic['message']}"
                target = result.errors if diagnostic["severity"] == "error" else result.warnings
                target.append(message)
        title = Title.model_validate({**raw, "scenes": compiled.get("scenes", {})})

    errors, warnings = check_title(title)
    result.errors += errors
    result.warnings += warnings
    result.title = title
    return result
