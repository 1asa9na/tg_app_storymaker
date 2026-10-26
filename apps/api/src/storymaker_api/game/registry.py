"""Собранный тайтл: данные, движок и хеш сборки."""

import hashlib
from dataclasses import dataclass

from storymaker_api.game.engine import Engine
from storymaker_api.game.schema import Title


@dataclass(frozen=True)
class TitleBuild:
    title: Title
    engine: Engine
    #: Хеш сборки: по нему сохранение понимает, что тайтл обновился.
    build: str

    @classmethod
    def from_json(cls, text: str) -> "TitleBuild":
        title = Title.model_validate_json(text)
        build = hashlib.sha256(text.encode()).hexdigest()[:16]
        return cls(title=title, engine=Engine(title), build=build)


def dump_title(title: Title) -> str:
    return title.model_dump_json(by_alias=True, exclude_defaults=True)
