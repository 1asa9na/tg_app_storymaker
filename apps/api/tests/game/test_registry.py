from pathlib import Path

from storymaker_api.game.registry import TitleBuild, dump_title, load_builds
from storymaker_api.game.schema import Title
from tests.game.conftest import TITLE


def test_build_round_trips_title(tmp_path: Path) -> None:
    title = Title.model_validate(TITLE)
    (tmp_path / "test.json").write_text(dump_title(title), encoding="utf-8")

    builds = load_builds(tmp_path)

    assert builds["test"].title == title
    assert builds["test"].title.scenes["anna_meet"].json_ == "{}"


def test_build_hash_changes_with_content() -> None:
    title = Title.model_validate(TITLE)
    renamed = Title.model_validate({**TITLE, "config": {**TITLE["config"], "name": "Другой"}})

    first = TitleBuild.from_json(dump_title(title))

    assert first.build == TitleBuild.from_json(dump_title(title)).build
    assert first.build != TitleBuild.from_json(dump_title(renamed)).build


def test_missing_directory_means_no_titles(tmp_path: Path) -> None:
    assert load_builds(tmp_path / "nope") == {}
    assert load_builds(None) == {}
