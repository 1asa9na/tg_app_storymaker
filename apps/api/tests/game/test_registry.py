from storymaker_api.game.registry import TitleBuild, dump_title
from storymaker_api.game.schema import Title
from tests.game.conftest import TITLE


def test_build_round_trips_title() -> None:
    title = Title.model_validate(TITLE)

    build = TitleBuild.from_json(dump_title(title))

    assert build.title == title
    assert build.title.scenes["anna_meet"].json_ == "{}"


def test_build_hash_changes_with_content() -> None:
    title = Title.model_validate(TITLE)
    renamed = Title.model_validate({**TITLE, "config": {**TITLE["config"], "name": "Другой"}})

    first = TitleBuild.from_json(dump_title(title))

    assert first.build == TitleBuild.from_json(dump_title(title)).build
    assert first.build != TitleBuild.from_json(dump_title(renamed)).build
