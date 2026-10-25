from datetime import UTC, datetime
from typing import Any

import pytest

from storymaker_api.game.engine import Engine
from storymaker_api.game.schema import Title

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)

#: Маленький тайтл для тестов движка: зал, кафе, Анна, энергия с восстановлением.
TITLE: dict[str, Any] = {
    "id": "test",
    "config": {
        "name": "Тест",
        "time": {
            "slots": [
                {"id": "morning", "name": "Утро"},
                {"id": "day", "name": "День"},
                {"id": "evening", "name": "Вечер"},
            ],
            "sleep_from": ["evening"],
            "days": 3,
            "week": ["пн", "вт", "ср"],
        },
        "resources": {
            "energy": {
                "name": "Энергия",
                "start": 50,
                "max": 50,
                "regen": {"amount": 1, "every_minutes": 6},
            },
            "money": {"name": "Деньги", "start": 10},
        },
        "stats": {"fitness": {"name": "Форма", "max": 10}},
        "start": {"location": "home", "items": {"rose": 1}},
    },
    "characters": {
        "anna": {
            "name": "Анна",
            "emotions": ["neutral", "happy"],
            "gifts": {"rose": 5},
            "schedule": [
                {"location": "gym", "slots": ["evening"]},
                {"location": "cafe", "weekdays": ["вт"]},
            ],
        }
    },
    "locations": {
        "home": {"name": "Дом", "background": "home"},
        "gym": {"name": "Зал", "background": "gym", "slots": ["morning", "evening"]},
        "cafe": {
            "name": "Кафе",
            "background": "cafe",
            "unlock_when": {"flag.met_anna": True},
            "locked_hint": "Сначала познакомьтесь с Анной",
        },
    },
    "activities": {
        "workout": {
            "name": "Тренировка",
            "location": "gym",
            "cost": {"slots": 1, "energy": 20},
            "effects": {"add": {"stat.fitness": 3, "global.xp": 5}},
        },
        "rest": {"name": "Отдых", "location": "home", "cost": {"slots": 1}},
        "talk": {
            "name": "Поговорить",
            "location": "gym",
            "with_character": "anna",
            "cost": {"slots": 0, "energy": 5},
            "effects": {"add": {"affection.anna": 2}},
        },
        "coffee": {
            "name": "Кофе",
            "location": "cafe",
            "cost": {"slots": 1, "money": 5},
            "requires": {"affection.anna": {"gte": 10}},
            "locked_hint": "Анна пока не согласится",
        },
    },
    "items": {
        "rose": {"name": "Роза", "kind": "gift"},
        "tea": {"name": "Чай", "kind": "consumable", "use": {"add": {"resource.energy": 15}}},
    },
    "quests": {
        "anna_trust": {
            "name": "Доверие Анны",
            "start_when": {"flag.met_anna": True},
            "stages": [
                {
                    "id": "talk",
                    "journal": "Поговорить с Анной",
                    "complete_when": {"affection.anna": {"gte": 4}},
                },
                {
                    "id": "gift",
                    "journal": "Подарить розу",
                    "complete_when": {"affection.anna": {"gte": 9}},
                },
            ],
            "rewards": {"add": {"global.xp": 50}, "achievement": "trusted"},
        }
    },
    "events": {
        "meet_anna": {
            "trigger": {"on": "enter", "location": "gym"},
            "when": {"time.slot": "evening"},
            "scene": "anna_meet",
            "effects": {"set": {"flag.met_anna": True}},
        },
        "first_workout": {
            "trigger": {"on": "activity", "activity": "workout"},
            "scene": "first_workout",
            "priority": 1,
        },
    },
    "achievements": {"trusted": {"name": "Доверие"}},
    "scenes": {
        "anna_meet": {
            "json": "{}",
            "effects": [{"op": "affection", "character": "anna", "delta": 1}],
        },
        "first_workout": {"json": "{}", "effects": []},
    },
}


@pytest.fixture
def engine() -> Engine:
    return Engine(Title.model_validate(TITLE))
