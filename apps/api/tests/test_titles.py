import random
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from storymaker_api.main import create_app
from storymaker_api.routes.titles import get_now
from tests.conftest import make_init_data
from tests.game.conftest import NOW


@pytest.fixture
def api(migrated_database: None) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_now] = lambda: NOW
    with TestClient(app) as client:
        user = {"id": random.randint(10**9, 10**10), "first_name": "Игрок"}
        client.headers["Authorization"] = f"tma {make_init_data(user)}"
        yield client


def act(api: TestClient, action: dict[str, Any], **extra: Any) -> Any:
    body = {"request_id": str(uuid.uuid4()), "action": action, **extra}
    return api.post("/api/titles/test/actions", json=body)


def ok(api: TestClient, action: dict[str, Any]) -> dict[str, Any]:
    response = act(api, action)
    assert response.status_code == 200, response.json()
    return response.json()


def test_state_starts_a_new_game(api: TestClient) -> None:
    body = api.get("/api/titles/test/state").json()

    assert body["revision"] == 0
    assert body["time"] == {"day": 1, "slot": "morning", "weekday": "пн"}
    assert body["here"]["location"] == "home"
    assert body["resources"]["energy"]["value"] == 50
    assert body["account"]["level"] == 1
    ok(api, {"type": "go", "location": "gym"})
    workout = next(
        a
        for a in api.get("/api/titles/test/state").json()["here"]["activities"]
        if a["id"] == "workout"
    )
    assert workout["effects"] == {"stat.fitness": 3, "global.xp": 5}
    assert workout["cost"] == {"slots": 1, "energy": 20}


def test_catalog_lists_titles_with_save(api: TestClient) -> None:
    def entry() -> dict[str, Any]:
        return next(t for t in api.get("/api/titles").json() if t["slug"] == "test")

    assert entry() == {"slug": "test", "name": "Тест", "days": 3, "cover": None, "save": None}
    api.get("/api/titles/test/state")
    assert entry()["save"] == {"day": 1, "finished": False}


def test_game_data_has_no_rules(api: TestClient) -> None:
    body = api.get("/api/titles/test/game").json()

    assert body["characters"]["anna"]["name"] == "Анна"
    assert body["locations"]["cafe"] == {"name": "Кафе", "background": "cafe"}
    assert body["gifts_per_day"] == 1
    assert "events" not in body and "scenes" not in body


def test_unknown_title_is_404(api: TestClient) -> None:
    assert api.get("/api/titles/nope/state").status_code == 404


def test_requires_init_data(migrated_database: None) -> None:
    with TestClient(create_app()) as client:
        assert client.get("/api/titles").status_code == 401


def test_action_applies_and_queues_scene(api: TestClient) -> None:
    ok(api, {"type": "go", "location": "gym"})
    body = ok(api, {"type": "activity", "id": "workout"})

    assert body["revision"] == 2
    assert body["time"]["slot"] == "day"
    assert body["pending_scene"] == "first_workout"
    assert body["outcome"]["xp"] == 5
    assert {"path": "stat.fitness", "delta": 3} in body["outcome"]["changes"]
    assert body["account"]["xp"] == 5

    blocked = act(api, {"type": "go", "location": "home"})
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "scene_pending"

    scene = api.get("/api/titles/test/scenes/first_workout")
    assert scene.status_code == 200 and scene.json()["json"] == "{}"
    assert api.get("/api/titles/test/scenes/anna_meet").status_code == 404

    done = ok(api, {"type": "scene_complete", "scene": "first_workout", "effects": []})
    assert done["pending_scene"] is None


def test_repeated_request_is_applied_once(api: TestClient) -> None:
    ok(api, {"type": "go", "location": "gym"})
    body = {
        "request_id": str(uuid.uuid4()),
        "action": {"type": "activity", "id": "workout"},
    }

    first = api.post("/api/titles/test/actions", json=body)
    second = api.post("/api/titles/test/actions", json=body)

    assert second.status_code == 200
    assert second.json() == first.json()
    state = api.get("/api/titles/test/state").json()
    assert state["revision"] == 2
    assert state["resources"]["energy"]["value"] == 30
    assert api.get("/api/profile").json()["xp"] == 5


def test_stale_revision_is_refused(api: TestClient) -> None:
    ok(api, {"type": "go", "location": "gym"})

    response = act(api, {"type": "go", "location": "home"}, revision=0)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stale"
    assert act(api, {"type": "go", "location": "home"}, revision=1).status_code == 200


def test_refused_action_changes_nothing(api: TestClient) -> None:
    response = act(api, {"type": "go", "location": "cafe"})

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "locked",
        "message": "Сначала познакомьтесь с Анной",
    }
    assert api.get("/api/titles/test/state").json()["revision"] == 0


def test_scene_cannot_grant_effects_outside_its_whitelist(api: TestClient) -> None:
    ok(api, {"type": "go", "location": "gym"})
    ok(api, {"type": "activity", "id": "workout"})

    response = act(
        api,
        {
            "type": "scene_complete",
            "scene": "first_workout",
            "effects": [{"op": "xp", "amount": 1000}],
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "effect_not_allowed"
    assert api.get("/api/profile").json()["xp"] == 5


def test_quest_reward_goes_to_account(api: TestClient) -> None:
    ok(api, {"type": "go", "location": "gym"})
    ok(api, {"type": "activity", "id": "workout"})
    ok(api, {"type": "scene_complete", "scene": "first_workout", "effects": []})
    ok(api, {"type": "go", "location": "home"})
    ok(api, {"type": "activity", "id": "rest"})
    ok(api, {"type": "go", "location": "gym"})
    ok(
        api,
        {
            "type": "scene_complete",
            "scene": "anna_meet",
            "effects": [{"op": "affection", "character": "anna", "delta": 1}],
        },
    )
    ok(api, {"type": "activity", "id": "talk"})
    ok(api, {"type": "activity", "id": "talk"})

    body = ok(api, {"type": "gift", "item": "rose", "character": "anna"})

    assert body["outcome"]["achievements"] == ["trusted"]
    assert body["outcome"]["xp"] == 50
    assert body["account"] == {
        "xp": 55,
        "level": 2,
        "level_xp": 50,
        "next_level_xp": 150,
        "level_up": True,
    }
    assert body["state"]["global_level"] == 2
    profile = api.get("/api/profile").json()
    assert profile["level"] == 2
    assert [(a["key"], a["name"], a["title"]) for a in profile["achievements"]] == [
        ("trusted", "Доверие", "test")
    ]
    assert api.get("/api/me").json()["level"] == 2


def test_restart_keeps_account_progress(api: TestClient) -> None:
    ok(api, {"type": "go", "location": "gym"})
    ok(api, {"type": "activity", "id": "workout"})

    response = api.post("/api/titles/test/restart", json={"request_id": str(uuid.uuid4())})

    assert response.status_code == 200
    body = response.json()
    assert body["time"]["slot"] == "morning"
    assert body["pending_scene"] is None
    assert body["revision"] == 3
    assert body["account"]["xp"] == 5
