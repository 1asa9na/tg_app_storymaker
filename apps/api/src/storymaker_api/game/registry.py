"""Опубликованные тайтлы: сборки в JSON, которые читает API.

До студии (этап 3) сборка — файл `<slug>.json`, который `python -m storymaker_api.game build`
делает из папки тайтла при сборке образа. В образе API нет Node: сцены уже скомпилированы.
"""

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

from storymaker_api.game.engine import Engine
from storymaker_api.game.schema import Title

logger = logging.getLogger(__name__)


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


def load_builds(directory: Path | None) -> dict[str, TitleBuild]:
    """Все сборки из папки; порядок каталога — по имени файла."""
    if directory is None:
        return {}
    if not directory.is_dir():
        logger.warning("titles directory %s does not exist", directory)
        return {}
    builds: dict[str, TitleBuild] = {}
    for path in sorted(directory.glob("*.json")):
        build = TitleBuild.from_json(path.read_text(encoding="utf-8"))
        builds[build.title.id] = build
    logger.info("loaded titles: %s", ", ".join(builds) or "none")
    return builds
