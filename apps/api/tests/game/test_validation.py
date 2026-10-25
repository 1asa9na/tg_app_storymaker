import copy
from pathlib import Path
from typing import Any

import yaml

from storymaker_api.game.loader import load_title
from storymaker_api.game.schema import Title
from storymaker_api.game.validation import check_title
from tests.game.conftest import TITLE


def errors_for(**changes: Any) -> list[str]:
    data = copy.deepcopy(TITLE)
    for section, value in changes.items():
        data[section] = {**data.get(section, {}), **value}
    errors, _ = check_title(Title.model_validate(data))
    return errors


def test_valid_title_has_no_errors() -> None:
    errors, warnings = check_title(Title.model_validate(TITLE))

    assert errors == []
    assert warnings == []


def test_reports_broken_references() -> None:
    errors = errors_for(
        activities={
            "swim": {
                "name": "Плавание",
                "location": "pool",
                "cost": {"oxygen": 5},
                "effects": {"add": {"stat.speed": 1}, "start_quest": "unknown"},
            }
        },
        events={"x": {"trigger": {"activity": "fly"}, "scene": "missing"}},
    )

    assert errors == [
        "activities.swim.location: локации «pool» нет в тайтле",
        "activities.swim.cost: ресурса «oxygen» нет в тайтле",
        "activities.swim.effects.add.stat.speed: характеристики «speed» нет в тайтле",
        "activities.swim.effects.start_quest: квеста «unknown» нет в тайтле",
        "events.x.trigger: занятия «fly» нет в тайтле",
        "events.x.scene: сцены «missing» нет в тайтле",
    ]


def test_reports_bad_conditions() -> None:
    errors = errors_for(
        locations={
            "park": {
                "name": "Парк",
                "background": "park",
                "unlock_when": {
                    "affection.anna": {"gte": "много"},
                    "time.slot": "night",
                    "quest.anna_trust": {"gt": "done"},
                    "weather": "rain",
                },
            }
        }
    )

    assert errors == [
        "locations.park.unlock_when.affection.anna: ожидается целое число, получено 'много'",
        "locations.park.unlock_when.time.slot: «night» — нет такого значения, "
        "можно: morning, day, evening",
        "locations.park.unlock_when.quest.anna_trust: оператор «gt» не подходит, можно: eq, in, ne",
        "locations.park.unlock_when.weather: неизвестный путь «weather»",
    ]


def test_warns_about_scenes_nobody_triggers() -> None:
    data = copy.deepcopy(TITLE)
    data["scenes"]["orphan"] = {"json": "{}", "effects": []}

    _, warnings = check_title(Title.model_validate(data))

    assert warnings == ["scenes/orphan.ink: сцену не запускает ни одно событие"]


def test_loader_explains_schema_errors_per_file(tmp_path: Path) -> None:
    (tmp_path / "title.yaml").write_text(
        yaml.safe_dump({"name": "Тест", "time": {"slots": [{"id": "Morning", "name": "Утро"}]}}),
        encoding="utf-8",
    )
    (tmp_path / "items.yaml").write_text(
        yaml.safe_dump({"rose": {"kind": "flower", "price": 3}}), encoding="utf-8"
    )

    result = load_title(tmp_path)

    assert result.title is None
    assert sorted(result.errors) == sorted(
        [
            "title.yaml → time → slots → 0 → id: "
            "ожидается ключ латиницей в нижнем регистре: a-z, 0-9, _",
            "items.yaml → rose → name: обязательное поле",
            "items.yaml → rose → kind: недопустимое значение",
            "items.yaml → rose → price: неизвестное поле",
        ]
    )
